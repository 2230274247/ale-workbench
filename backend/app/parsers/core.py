"""Pure preview parsers. Decimal values are JSON strings; issues prohibit blind DB writes.

Add a content-recognising parser in parse_file; never infer scientific units from names.
No filesystem, database, application configuration or persistence dependencies.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
from io import BytesIO
import hashlib
import json
import re
import zipfile
from defusedxml import ElementTree as ET
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

VERSION = '1.1.0'
MAX_BYTES = 25 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
MAX_SHEETS = 16
MAX_ROWS = 10000
MAX_COLUMNS = 256
MAX_CELLS = 100000                 # Actual XML cells, across the entire workbook.
MAX_GRID_CELLS = 200000            # Rectangles openpyxl would fill, across all sheets.
MAX_POINTS = 10000                 # Across all blocks and sheets.
MAX_OUTPUT_BYTES = 16 * 1024 * 1024 # UTF-8 JSON, including raw data and issues.
MAX_CELL_TEXT = 8192
MAX_XML_NODES = 1000000
MAX_XML_DEPTH = 64
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
FIELDS = {'No': 'point_no', 'x(mm)': 'x_mm', 'y(mm)': 'y_mm',
          'Intensity': 'intensity', 'Height(mm)': 'height_mm', 'MSE': 'mse',
          'GOF': 'gof', 'layer_1_thickness(nm)': 'thickness_nm', 'AOI': 'aoi_deg',
          'FitIter': 'fit_iter', 'LBH': 'lbh', 'FitTime(ms)': 'fit_time_ms'}
DECIMALS = {'x_mm': (12, 6), 'y_mm': (12, 6), 'thickness_nm': (14, 6),
            'intensity': (16, 6), 'height_mm': (12, 6), 'mse': (14, 6),
            'gof': (16, 10), 'aoi_deg': (8, 3), 'lbh': (12, 6), 'fit_time_ms': (12, 3)}
SUMMARY = {'Max', 'Min', 'Average', 'Max-Min', '(Max-Min)/(Max+Min)',
           '(Max-Min)/2*Average', 'stdDev', 'Uniformity(%)', 'Uniformity2(%: STD/AVG)'}


def issue(code, message, locator=None, field=None):
    return {'code': code, 'message': message, 'locator': locator, 'field': field}


def decimal_value(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
        return d if d.is_finite() and len(d.as_tuple().digits) <= 100 and abs(d.adjusted()) <= 100 else None
    except (InvalidOperation, ValueError):
        return None


def stats(points):
    """50 significant digits, ROUND_HALF_EVEN context; no DB-scale rounding."""
    result = {'point_count': len(points), 'includes_outliers': True,
              'sd_convention': {'sample': 'n-1; null for n<2', 'population': 'n'},
              'decimal_precision': 50, 'rounding': 'ROUND_HALF_EVEN',
              'db_write_policy': 'Derived decimals require explicit DB-scale conversion confirmation.'}
    with localcontext() as ctx:
        ctx.prec = 50
        ctx.rounding = ROUND_HALF_EVEN
        for field in ('thickness_nm', 'mse', 'gof'):
            values = [decimal_value(p[field]) for p in points]
            values = [v for v in values if v is not None]
            n = len(values)
            if not n:
                result[field] = {'count': 0, 'excluded_nonfinite_or_missing': len(points)}
                continue
            mean = sum(values) / n
            ss = sum((v - mean) ** 2 for v in values)
            result[field] = {'count': n, 'excluded_nonfinite_or_missing': len(points)-n,
                             'mean': str(mean), 'min': str(min(values)), 'max': str(max(values)),
                             'sd_sample': str((ss / (n-1)).sqrt()) if n > 1 else None,
                             'sd_population': str((ss / n).sqrt())}
    return result


def _mark(point, note):
    point['is_outlier'] = True
    point['outlier_note'] = '; '.join(filter(None, (point['outlier_note'], note)))


def mark_outliers(points):
    values = sorted(decimal_value(p['thickness_nm']) for p in points if decimal_value(p['thickness_nm']) is not None)
    if len(values) < 4:
        return
    def median(a):
        n = len(a)
        return a[n//2] if n % 2 else (a[n//2-1] + a[n//2]) / 2
    with localcontext() as ctx:
        ctx.prec = 110
        q1 = median(values[:len(values)//2]); q3 = median(values[(len(values)+1)//2:])
        low = q1 - Decimal('1.5')*(q3-q1); high = q3 + Decimal('1.5')*(q3-q1)
        for p in points:
            d = decimal_value(p['thickness_nm'])
            if d is not None and (d < low or d > high):
                _mark(p, 'Tukey 1.5 IQR; median of halves (odd centre excluded); retained in statistics')


class PreviewLimit(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise PreviewLimit(code, message)


class _ExpandedReader:
    """Count bytes actually inflated, including XML parts openpyxl will later read."""
    def __init__(self, stream, budget):
        self.stream = stream
        self.budget = budget

    def read(self, size=-1):
        # iterparse uses bounded reads; non-XML members are drained in bounded chunks.
        data = self.stream.read(min(size, 65536) if size >= 0 else 65536)
        self.budget[0] += len(data)
        if self.budget[0] > MAX_EXPANDED:
            _fail('expanded_size_limit', 'Actual expanded archive exceeds 100 MiB')
        return data


def _coordinate(value):
    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', value or '')
    if not match:
        _fail('invalid_coordinate', 'Explicit, canonical XML cell coordinates required')
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - ord('A') + 1
    row = int(match[2])
    if row > MAX_ROWS or column > MAX_COLUMNS:
        _fail('sheet_limit', 'Actual XML row must be <=10000 and column <=256')
    return row, column


def _json_size(value):
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(value):
        size += len(chunk.encode('utf-8'))
        if size > MAX_OUTPUT_BYTES:
            _fail('output_size_limit', 'Preview JSON exceeds 16 MiB')
    return size


class _OutputBudget:
    def __init__(self):
        self.size = 0
        self.points = 0

    def add(self, value):
        self.size += _json_size(value)
        if self.size > MAX_OUTPUT_BYTES:
            _fail('output_size_limit', 'Preview JSON exceeds 16 MiB')


def _preflight_workbook(archive):
    """Stream and clear XML before openpyxl can trust dimensions or allocate grids.

    No worksheet tree is retained. All parts (also shared strings/styles/unused sheets)
    are scanned and all ZIP members are inflated under one archive-wide byte budget.
    """
    infos = archive.infolist()
    if len({i.filename for i in infos}) != len(infos):
        _fail('duplicate_zip_member', 'Duplicate ZIP member names are ambiguous')
    if sum(i.file_size for i in infos) > MAX_EXPANDED:
        _fail('expanded_size_limit', 'Expanded preview limit 100 MiB')
    expanded = [0]
    sheets = {}
    cell_count = grid_count = node_count = declared_sheets = candidate_rows = 0
    output_estimate = shared_references = max_shared_bytes = 0
    shared_bytes = 0
    for info in infos:
        with archive.open(info) as stream:
            reader = _ExpandedReader(stream, expanded)
            if not info.filename.endswith(('.xml', '.rels')):
                while reader.read(65536):
                    pass
                continue
            stack = []
            worksheet = False
            dimension = None
            lexical = {}
            row_number = last_row = last_column = 0
            bounds = None
            for event, element in ET.iterparse(reader, events=('start', 'end'),
                                               forbid_dtd=True, forbid_entities=True,
                                               forbid_external=True):
                if event == 'start':
                    stack.append(element)
                    node_count += 1
                    if node_count > MAX_XML_NODES or len(stack) > MAX_XML_DEPTH:
                        _fail('xml_complexity_limit', 'XML node/depth budget exceeded')
                    if any(len(v) > MAX_CELL_TEXT for v in element.attrib.values()):
                        _fail('cell_text_limit', 'XML attribute exceeds 8192 characters')
                    if len(stack) == 1:
                        worksheet = element.tag == NS+'worksheet'
                        if worksheet and len(sheets) >= MAX_SHEETS:
                            _fail('sheet_count_limit', 'At most 16 worksheets per workbook')
                    if info.filename == 'xl/workbook.xml' and element.tag == NS+'sheet':
                        declared_sheets += 1
                        if declared_sheets > MAX_SHEETS:
                            _fail('sheet_count_limit', 'At most 16 declared sheets per workbook')
                    if element.tag == NS+'si':
                        shared_bytes = 0
                    if not worksheet:
                        continue
                    if element.tag == NS+'dimension':
                        if dimension is not None:
                            _fail('dimension_mismatch', 'Duplicate worksheet dimension')
                        dimension = element.get('ref', '')
                    elif element.tag == NS+'row':
                        value = element.get('r', '')
                        if not re.fullmatch(r'[1-9][0-9]{0,6}', value):
                            _fail('invalid_coordinate', 'Explicit XML row coordinates required')
                        row_number = int(value)
                        if row_number > MAX_ROWS:
                            _fail('sheet_limit', 'Actual XML row exceeds 10000')
                        if row_number <= last_row:
                            _fail('invalid_coordinate', 'Rows must be unique and ascending')
                        candidate_rows += 1
                        if candidate_rows > MAX_POINTS:
                            _fail('point_count_limit', 'Workbook exceeds 10000 candidate XML rows (point budget)')
                        last_row = row_number
                        last_column = 0
                    elif element.tag == NS+'c':
                        if len(stack) < 3 or stack[-2].tag != NS+'row':
                            _fail('invalid_coordinate', 'Cell outside worksheet row')
                        row, column = _coordinate(element.get('r'))
                        if row != row_number or column <= last_column:
                            _fail('invalid_coordinate', 'Cells must match row and ascend uniquely')
                        last_column = column
                        cell_count += 1
                        if cell_count > MAX_CELLS:
                            _fail('cell_count_limit', 'Workbook exceeds 100000 actual XML cells')
                        if bounds is None:
                            bounds = [row, column, row, column]
                        else:
                            bounds = [min(bounds[0], row), min(bounds[1], column),
                                      max(bounds[2], row), max(bounds[3], column)]
                        # Reject before openpyxl allocates sparse rectangular padding.
                        if grid_count + bounds[2] * bounds[3] > MAX_GRID_CELLS:
                            _fail('grid_cell_limit', 'Workbook exceeds 200000 padded grid cells')
                else:
                    if len(element.text or '') > MAX_CELL_TEXT or len(element.tail or '') > MAX_CELL_TEXT:
                        _fail('cell_text_limit', 'XML text exceeds 8192 characters')
                    if not worksheet and element.tag == NS+'t':
                        shared_bytes += len((element.text or '').encode('utf-8'))
                        if shared_bytes > MAX_CELL_TEXT * 4:
                            _fail('cell_text_limit', 'Shared string exceeds text budget')
                    if not worksheet and element.tag == NS+'si':
                        max_shared_bytes = max(max_shared_bytes, shared_bytes)
                    if worksheet and element.tag == NS+'c':
                        if element.get('t') == 's':
                            shared_references += 1
                        # Conservative output allowance for raw cells, typed fields, locators
                        # and issues, before any rectangular padding/openpyxl allocation.
                        text_bytes = sum(len((e.text or '').encode('utf-8')) for e in element.iter())
                        output_estimate += 512 + 12 * text_bytes
                        if output_estimate > MAX_OUTPUT_BYTES:
                            _fail('output_size_limit', 'Conservative preview output budget exceeds 16 MiB')
                        formulas = element.findall(NS+'f')
                        values = element.findall(NS+'v')
                        if len(formulas) > 1 or len(values) > 1:
                            _fail('invalid_cell', 'Duplicate formula/cache elements')
                        if formulas:
                            lexical[element.get('r')] = {
                                'formula': '=' + (formulas[0].text or ''),
                                'formula_attributes': dict(formulas[0].attrib),
                                'cached_value_lexeme': values[0].text if values else None,
                                'cached_type': element.get('t', 'n'),
                                'cache_present': bool(values)}
                        elif element.get('t', 'n') == 'n' and values:
                            lexical[element.get('r')] = values[0].text
                    # Keep only a cell's tiny subtree until its end event (formula/v).
                    in_cell = worksheet and any(e.tag == NS+'c' for e in stack[:-1])
                    if not in_cell:
                        element.clear()
                        if len(stack) > 1:
                            stack[-2].remove(element)
                    stack.pop()
            if worksheet:
                if dimension is None:
                    _fail('dimension_missing', 'Worksheet dimension missing; retain original only')
                parts = dimension.split(':')
                if len(parts) not in (1, 2):
                    _fail('dimension_mismatch', 'Invalid worksheet dimension')
                first = _coordinate(parts[0]); last = _coordinate(parts[-1])
                expected = tuple(bounds) if bounds else (1, 1, 1, 1)
                if (*first, *last) != expected or last_row > last[0]:
                    _fail('dimension_mismatch', 'Declared dimension differs from actual XML coordinates')
                grid_count += last[0] * last[1]
                if grid_count > MAX_GRID_CELLS:
                    _fail('grid_cell_limit', 'Workbook exceeds 200000 padded grid cells')
                sheets[info.filename] = lexical
    # Shared strings may appear after worksheet ZIP members. Count every use before
    # openpyxl expands references; use max entry size to avoid retaining another tree.
    if output_estimate + shared_references * max_shared_bytes * 12 > MAX_OUTPUT_BYTES:
        _fail('output_size_limit', 'Shared string expansion exceeds conservative output budget')
    return sheets


def _raw(cell, lexical):
    coordinate = getattr(cell, 'coordinate', None)
    v = lexical.get(coordinate, cell.value)
    if isinstance(v, dict):
        return {'value': cell.value, 'cell': coordinate, 'data_type': 'f', **v}
    if v is not None and not isinstance(v, (str, int, bool)):
        v = str(v)
    return {'value': v, 'cell': coordinate, 'data_type': cell.data_type}


def parse_eoptics(content, result):
    with zipfile.ZipFile(BytesIO(content)) as archive:
        raw_sheets = _preflight_workbook(archive)
        budget = _OutputBudget()
        for path, lexical in raw_sheets.items():
            for coordinate, value in lexical.items():
                if isinstance(value, dict):
                    result['blocking_issues'].append(issue('untrusted_formula',
                        'Formula/cache preserved without evaluation; original cache is not trusted',
                        {'worksheet_part': path, 'cell': coordinate}))
        budget.add(result)
        wb = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            for sheet in wb:
                path = sheet._worksheet_path.lstrip('/')
                if path not in raw_sheets:
                    _fail('unverified_worksheet', 'Worksheet was not streamed during preflight')
                rows = list(sheet.iter_rows())
                lexical = raw_sheets[path]
                # No partially validated multi-layer workbook may expose importable points.
                for row in rows:
                    for cell in row:
                        label = str(cell.value).strip() if cell.value is not None else ''
                        match = re.fullmatch(r'layer_(\d+)_thickness(?:\(.*\))?', label, re.I)
                        if match and match[1] != '1':
                            _fail('unverified_multilayer', 'Multiple/unverified layer thickness columns; original only')
                company = any(str(c.value).strip().lower() == 'eoptics' for row in rows[:20] for c in row)
                headers = [i for i, row in enumerate(rows) if any(c.value == 'No' for c in row)
                           and any(str(c.value).startswith('layer_1_thickness') for c in row)]
                if not company or not headers:
                    result['warnings'].append(issue('unrecognised_sheet', 'Sheet retained in original only; no verified Eoptics block', {'sheet': sheet.title}))
                    continue
                for hi, start in enumerate(headers):
                    end = headers[hi+1] if hi+1 < len(headers) else len(rows)
                    header = rows[start]; labels = [str(c.value).strip() if c.value is not None else '' for c in header]
                    locator = {'sheet': sheet.title, 'header_row': start+1, 'end_row': end}
                    block = {'metadata': {'instrument': 'Eoptics', 'headers': labels,
                              'units': {'thickness_nm': 'nm', 'x_mm': 'mm', 'y_mm': 'mm', 'height_mm': 'mm',
                                        'fit_time_ms': 'ms', 'aoi_deg': None, 'lbh': None},
                              'preamble': [[_raw(c, lexical) for c in row if c.value is not None] for row in rows[:start]],
                              'instrument_summary': [], 'optical_model': {'source': 'workbook_content',
                              'parameter_columns': [v for v in labels if re.fullmatch(r'\d+#M_\d+@.+', v)],
                              'n': None, 'k': None, 'note': 'Dispersion parameters retained per point; n/k are not inferred from filenames or evaluated without wavelength/model definition.'}},
                             'points': [], 'statistics': {}, 'warnings': [], 'blocking_issues': [], 'locator': locator}
                    duplicate_headers = [k for k, n in Counter(labels).items() if k and n > 1]
                    if duplicate_headers:
                        block['blocking_issues'].append(issue('duplicate_headers', str(duplicate_headers), locator))
                    for required in ('No', 'x(mm)', 'y(mm)', 'layer_1_thickness(nm)', 'MSE', 'GOF'):
                        if required not in labels:
                            block['blocking_issues'].append(issue('missing_or_unknown_unit_column', required, locator))
                    if 'AOI' in labels:
                        block['warnings'].append(issue('aoi_unit_unconfirmed', 'AOI header has no explicit degree unit; raw AOI retained, aoi_deg null pending confirmation', locator, 'aoi_deg'))
                    if 'LBH' in labels:
                        block['warnings'].append(issue('lbh_unit_unconfirmed', 'LBH semantic/unit requires confirmation; raw retained', locator, 'lbh'))
                    budget.add(block)
                    seen = {}
                    for source_row, row in enumerate(rows[start+1:end], start=start+2):
                        if not any(c.value is not None for c in row):
                            continue
                        raw = [_raw(c, lexical) for c in row]
                        issue_start = len(block['blocking_issues'])
                        warning_start = len(block['warnings'])
                        for entry in raw:
                            if entry.get('data_type') == 'f':
                                block['blocking_issues'].append(issue('untrusted_formula',
                                    'Formula and cache retained without evaluation; cache is not trusted',
                                    {'sheet': sheet.title, 'cell': entry['cell']}))
                        for j, entry in enumerate(raw):
                            entry['cell'] = entry['cell'] or f'{get_column_letter(j+1)}{source_row}'
                        no_index = labels.index('No')
                        tag = str(row[no_index].value).strip() if no_index < len(row) else ''
                        if tag in SUMMARY:
                            block['metadata']['instrument_summary'].append({'label': tag, 'source_row': source_row, 'raw_values': raw})
                            budget.add(block['metadata']['instrument_summary'][-1])
                            budget.add(block['blocking_issues'][issue_start:])
                            continue
                        budget.points += 1
                        if budget.points > MAX_POINTS:
                            _fail('point_count_limit', 'Workbook exceeds 10000 preview points')
                        p = {field: None for field in FIELDS.values()}
                        p.update({'dispersion_params': {}, 'source_sheet': sheet.title, 'source_row': source_row,
                                  'source_cell': None, 'is_outlier': False, 'outlier_note': None,
                                  'raw_values': raw, 'locator': {'sheet': sheet.title, 'row': source_row}})
                        for j, label in enumerate(labels):
                            if j >= len(row):
                                continue
                            cell = row[j]; value = raw[j]['value']; field = FIELDS.get(label)
                            if re.fullmatch(r'\d+#M_\d+@.+', label):
                                d = decimal_value(value)
                                p['dispersion_params'][label] = str(d) if d is not None else None
                                if d is None:
                                    block['blocking_issues'].append(issue('invalid_model_parameter', label, {'sheet': sheet.title, 'cell': raw[j]['cell']}))
                                    _mark(p, 'invalid model parameter '+label)
                            if field is None:
                                continue
                            if field == 'thickness_nm':
                                p['source_cell'] = raw[j]['cell']
                            if field in ('aoi_deg', 'lbh'):
                                continue
                            d = decimal_value(value) if cell.data_type != 'f' else None
                            loc = {'sheet': sheet.title, 'cell': raw[j]['cell']}
                            if d is None:
                                block['blocking_issues'].append(issue('invalid_numeric', 'Missing, formula, nonnumeric, nonfinite or excessive numeric value; raw retained', loc, field))
                                _mark(p, 'invalid '+field)
                                continue
                            if field in ('point_no', 'fit_iter'):
                                if d != d.to_integral_value() or not 0 <= d <= 4294967295:
                                    block['blocking_issues'].append(issue('invalid_unsigned_integer', 'Requires unsigned 32-bit integer', loc, field)); _mark(p, 'invalid '+field)
                                else:
                                    p[field] = int(d)
                            else:
                                p[field] = str(d)
                                precision, scale = DECIMALS[field]
                                with localcontext() as ctx:
                                    ctx.prec = 210
                                    exact = d == d.quantize(Decimal(1).scaleb(-scale))
                                if not exact or abs(d) >= Decimal(10)**(precision-scale):
                                    block['blocking_issues'].append(issue('db_decimal_confirmation_required', f'DECIMAL({precision},{scale}) cannot represent original exactly; no rounding performed', loc, field))
                            if field in ('thickness_nm', 'mse') and d < 0:
                                _mark(p, 'negative '+field)
                                block['warnings'].append(issue('negative_value', 'Retained for review', loc, field))
                        no = p['point_no']
                        if no is not None:
                            if no in seen:
                                _mark(p, 'duplicate point_no'); _mark(seen[no], 'duplicate point_no')
                                block['blocking_issues'].append(issue('duplicate_point_no', 'All occurrences retained; UNIQUE DB key requires confirmation', p['locator'], 'point_no'))
                            else:
                                seen[no] = p
                        if p['thickness_nm'] is None:
                            _mark(p, 'missing or unconfirmed thickness')
                        budget.add(p)
                        budget.add(block['blocking_issues'][issue_start:])
                        budget.add(block['warnings'][warning_start:])
                        block['points'].append(p)
                    mark_outliers(block['points'])
                    block['statistics'] = stats(block['points'])
                    if not block['points']:
                        block['blocking_issues'].append(issue('no_points', 'No measurement rows', locator))
                    budget.add(block['statistics'])
                    result['blocks'].append(block)
        finally:
            wb.close()
    if result['blocks']:
        result.update(type='eoptics', parser='eoptics_workbook')
    return result


def parse_file(content: bytes, filename: str) -> dict:
    """Read-only JSON preview. Caller stores original bytes separately by SHA256.

    status=needs_confirmation if ANY block/top-level blocking issue exists.
    original_only always has blocks=[]; rejected includes lock files.
    Filename hints must never populate measurement/model metadata automatically.
    """
    if not isinstance(content, bytes) or not isinstance(filename, str):
        raise TypeError('parse_file requires bytes and str')
    basename = filename.replace('\\', '/').rsplit('/', 1)[-1]
    result = {'type': 'unsupported', 'parser': 'original_only', 'version': VERSION,
              'status': 'original_only', 'blocks': [], 'warnings': [], 'blocking_issues': [],
              'filename_hints': {'source': 'filename_only', 'requires_confirmation': True,
                                 'n': None, 'k': None},
              'source': {'filename': filename, 'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}}
    match = re.search(r'(?:^|[-_])n([0-9]+(?:\.[0-9]+)?)[-_]k([0-9]+(?:\.[0-9]+)?)', basename, re.I)
    if match:
        result['filename_hints'].update(n=match[1], k=match[2])
    if basename.startswith('~$'):
        result['status'] = 'rejected'; result['blocking_issues'].append(issue('office_lock_file', 'Office temporary lock file rejected')); return result
    if len(content) > MAX_BYTES:
        result['blocking_issues'].append(issue('file_size_limit', 'Preview limit 25 MiB')); return result
    try:
        if zipfile.is_zipfile(BytesIO(content)):
            with zipfile.ZipFile(BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_EXPANDED:
                    result['blocking_issues'].append(issue('expanded_size_limit', 'Expanded preview limit 100 MiB')); return result
                names = set(z.namelist())
            if '[Content_Types].xml' in names and 'xl/workbook.xml' in names:
                parse_eoptics(content, result)
            else:
                result['warnings'].append(issue('zip_batch_unsupported', 'Batch ZIP preview unsupported; retain original'))
        elif content.lstrip().startswith(b'<'):
            root = ET.fromstring(content)
            if root.tag == 'Chart' and root.find('Series') is not None:
                result.update(type='xps_chart_configuration', parser='xps_chart_inspection')
                axes = [{ 'axis': e.tag, 'title': e.get('Title')} for e in root.iter() if e.tag in ('AxisX', 'AxisY', 'AxisY2')]
                # Actual verified exports contain configuration only, not sampled spectra.
                result['preview_metadata'] = {'axes': axes, 'root': root.tag,
                                              'data_series_count': len(root.findall("./Series/Series[@ChartType='Line']"))}
                result['warnings'].append(issue('no_verified_spectrum', 'Chart configuration is not a verified spectrum data format; no channels produced'))
            else:
                result['warnings'].append(issue('xml_schema_unverified', 'XML schema not verified; retain original'))
        elif content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            result['preview_metadata'] = {'container': 'OLE Compound File'}
            result['warnings'].append(issue('ole_format_unverified', 'VGD/legacy XLS proprietary contents not supported; retain original'))
        else:
            result['warnings'].append(issue('unsupported_content', 'No verified parser for content; retain original'))
    except PreviewLimit as exc:
        result.update(type='unsupported', parser='original_only', blocks=[], status='original_only')
        result['blocking_issues'].append(issue(exc.code, str(exc)))
    except Exception as exc:
        # A damaged file must remain previewable as an original without partial fake data.
        result.update(type='unsupported', parser='original_only', blocks=[])
        result['blocking_issues'].append(issue('invalid_file', type(exc).__name__ + ': ' + str(exc)[:300]))
    try:
        _json_size(result)
    except PreviewLimit as exc:
        result.update(type='unsupported', parser='original_only', blocks=[], status='original_only')
        result['blocking_issues'].append(issue(exc.code, str(exc)))
    if result['blocks']:
        blocked = result['blocking_issues'] or any(b['blocking_issues'] for b in result['blocks'])
        result['status'] = 'needs_confirmation' if blocked else 'parsed'
    return result
