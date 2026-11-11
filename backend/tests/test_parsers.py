"""No DB fixtures. Synthetic edge cases plus optional read-only real ZIP corpus.

Run independently of parent DB conftest using pytest --confcutdir=.../app/parsers
or unittest via this module. Real corpus: ALE_PARSER_UPLOADS=/path/to/uploads.
"""
import hashlib
import io
import json
import os
import re
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from decimal import Decimal
from openpyxl import Workbook
from app.parsers import parse_file
from app.parsers import core


def workbook(rows=None, headers=None, sheets=1):
    w = Workbook()
    for i in range(sheets):
        s = w.active if i == 0 else w.create_sheet('Repeat')
        s.append(['Company:', 'Eoptics'])
        s.append(headers or ['No', 'x(mm)', 'y(mm)', 'MSE', 'GOF', 'layer_1_thickness(nm)', '1#M_0@Einf'])
        for row in rows or [[1, '0', '0', '1.2', '0.99', '30.125', '1.1']]:
            s.append(row)
    b = io.BytesIO(); w.save(b); return b.getvalue()


def rewrite_workbook(data, transform):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
        for name in source.namelist():
            target.writestr(name, transform(name, source.read(name)))
    return output.getvalue()


def rewrite_sheet(data, transform):
    return rewrite_workbook(data, lambda name, value: transform(value)
                            if name.startswith('xl/worksheets/') else value)


class ParserTests(unittest.TestCase):
    def test_content_priority_and_hints(self):
        r = parse_file(workbook(), 'n1.9-k0.001.xml')
        self.assertEqual(r['type'], 'eoptics')
        self.assertEqual(r['status'], 'parsed')
        self.assertEqual(r['filename_hints']['n'], '1.9')
        self.assertIsNone(r['blocks'][0]['metadata']['optical_model']['n'])
        self.assertEqual(r['blocks'][0]['points'][0]['dispersion_params']['1#M_0@Einf'], '1.1')
        json.dumps(r, allow_nan=False)

    def test_invalid_thickness_rows_retained(self):
        for value in (None, 'bad', 'NaN', 'inf', '-Infinity', '=1+1'):
            with self.subTest(value=value):
                r = parse_file(workbook([[1, '0', '0', '1', '.9', value, '1']]), 'a.xlsx')
                p = r['blocks'][0]['points'][0]
                self.assertIsNone(p['thickness_nm']); self.assertTrue(p['is_outlier'])
                self.assertEqual(p['raw_values'][5]['value'], value)
                self.assertEqual(p['source_cell'], 'F3')
                self.assertEqual(r['status'], 'needs_confirmation')
                json.dumps(r, allow_nan=False)

    def test_duplicate_and_precision_no_rounding(self):
        r = parse_file(workbook([[1, '0.1234567', 0, 1, '.9', '30.0000001', 1],
                                [1, 0, 0, 2, '.8', 31, 1]]), 'x.xlsx')
        b = r['blocks'][0]
        self.assertEqual(len(b['points']), 2)
        self.assertTrue(all(p['is_outlier'] for p in b['points']))
        self.assertEqual(b['points'][0]['thickness_nm'], '30.0000001')
        codes = {i['code'] for i in b['blocking_issues']}
        self.assertIn('duplicate_point_no', codes)
        self.assertIn('db_decimal_confirmation_required', codes)

    def test_statistics_and_summary(self):
        rows = [[i+1, 0, 0, 1, '.9', v, 1] for i, v in enumerate([1, 2, 3])]
        rows.append(['Average', None, None, 'nan', None, '999', None])
        b = parse_file(workbook(rows), 'x.xlsx')['blocks'][0]
        self.assertEqual(len(b['points']), 3)
        self.assertEqual(len(b['metadata']['instrument_summary']), 1)
        s = b['statistics']['thickness_nm']
        self.assertEqual(Decimal(s['mean']), Decimal(2))
        self.assertEqual(Decimal(s['sd_sample']), Decimal(1))
        self.assertLess(Decimal(s['sd_population']), Decimal(1))

    def test_unknown_units_do_not_guess(self):
        b = parse_file(workbook(headers=['No', 'x', 'y', 'MSE', 'GOF', 'layer_1_thickness', 'AOI']), 'x.xlsx')['blocks'][0]
        self.assertIsNone(b['points'][0]['thickness_nm'])
        self.assertIsNone(b['points'][0]['x_mm'])
        self.assertIsNone(b['points'][0]['aoi_deg'])
        self.assertTrue(b['blocking_issues'])

    def test_multiple_sheets(self):
        self.assertEqual(len(parse_file(workbook(sheets=2), 'x.xlsx')['blocks']), 2)

    def test_tukey_retains_and_includes_outlier(self):
        rows = [[i+1, 0, 0, 1, '.9', v, 1] for i, v in enumerate([1, 1, 1, 1, 1, 100])]
        b = parse_file(workbook(rows), 'x.xlsx')['blocks'][0]
        self.assertEqual(len(b['points']), 6)
        self.assertTrue(b['points'][-1]['is_outlier'])
        self.assertEqual(Decimal(b['statistics']['thickness_nm']['mean']), Decimal('17.5'))

    def test_locks_corruption_unsupported_and_xml_entities(self):
        for content, filename, status in [(b'x', '~$x.xlsx', 'rejected'),
            (b'random RGA', 'rga.txt', 'original_only'),
            (b'<broken', 'x.xml', 'original_only'),
            (b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', 'x.xml', 'original_only')]:
            r = parse_file(content, filename)
            self.assertEqual(r['status'], status); self.assertEqual(r['blocks'], [])
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z: z.writestr('x.txt', 'x')
        self.assertEqual(parse_file(b.getvalue(), 'archive.zip')['warnings'][0]['code'], 'zip_batch_unsupported')

    def test_unsigned_and_overflow(self):
        b = parse_file(workbook([[-1, '1000000', 0, 1, '.9', 30, 1]]), 'x')['blocks'][0]
        self.assertIsNone(b['points'][0]['point_no'])
        self.assertTrue(b['blocking_issues'])

    def test_numeric_xml_lexeme_preserved(self):
        data = workbook([[1, 0.1, 0, 1, .9, 30, 1]])
        src = zipfile.ZipFile(io.BytesIO(data)); out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for name in src.namelist():
                b = src.read(name)
                if name == 'xl/worksheets/sheet1.xml':
                    b = b.replace(b'<v>0.1</v>', b'<v>0.1234567890123456789</v>')
                z.writestr(name, b)
        p = parse_file(out.getvalue(), 'x')['blocks'][0]['points'][0]
        self.assertEqual(p['x_mm'], '0.1234567890123456789')
        self.assertEqual(p['raw_values'][1]['value'], '0.1234567890123456789')

    def assert_preflight_rejected(self, data, code):
        with patch.object(core, 'load_workbook', side_effect=AssertionError('must not load')) as loader:
            result = parse_file(data, 'edge.xlsx')
        loader.assert_not_called()
        self.assertEqual(result['status'], 'original_only')
        self.assertEqual(result['blocks'], [])
        self.assertIn(code, {i['code'] for i in result['blocking_issues']}, result)
        return result

    def test_dimension_undersize_cannot_drop_row4(self):
        data = workbook([[1, 0, 0, 1, .9, 30, 1], [2, 0, 0, 1, .9, 31, 1]])
        data = rewrite_sheet(data, lambda b: re.sub(rb'<dimension ref="[^"]+"\s*/>',
                                                   b'<dimension ref="A1:F3"/>', b))
        self.assert_preflight_rejected(data, 'dimension_mismatch')

    def test_missing_dimension_sparse_row_cannot_bypass_limit(self):
        for sparse in (False, True):
            with self.subTest(sparse=sparse):
                def alter(b):
                    b = re.sub(rb'<dimension ref="[^"]+"\s*/>', b'', b)
                    return b.replace(b'r="3"', b'r="100005"').replace(b'3"', b'100005"') if sparse else b
                self.assert_preflight_rejected(rewrite_sheet(workbook(), alter),
                                               'sheet_limit' if sparse else 'dimension_missing')

    def test_actual_coordinates_and_oversize_dimension(self):
        for before, after, code in [(b'r="F3"', b'r="IW3"', 'sheet_limit'),
                                     (b'r="F3"', b'r="F4"', 'invalid_coordinate'),
                                     (b'A1:G3', b'A1:G4', 'dimension_mismatch')]:
            with self.subTest(after=after):
                self.assert_preflight_rejected(rewrite_sheet(workbook(), lambda b: b.replace(before, after)), code)

    def test_sheet_count_before_openpyxl(self):
        self.assert_preflight_rejected(workbook(sheets=17), 'sheet_count_limit')

    def test_multisheet_cumulative_actual_cells_and_grid(self):
        for constant, limit, code in [('MAX_CELLS', 20, 'cell_count_limit'),
                                      ('MAX_GRID_CELLS', 30, 'grid_cell_limit'),
                                      ('MAX_POINTS', 5, 'point_count_limit')]:
            with self.subTest(constant=constant), patch.object(core, constant, limit):
                self.assert_preflight_rejected(workbook(sheets=2), code)

    def test_sparse_grid_before_openpyxl(self):
        data = rewrite_sheet(workbook(), lambda b: b.replace(b'A1:G3', b'A1:IV10000')
                             .replace(b'</sheetData>', b'<row r="10000"><c r="IV10000"><v>1</v></c></row></sheetData>'))
        self.assert_preflight_rejected(data, 'grid_cell_limit')

    def test_multilayer_original_only_even_if_other_sheet_parses(self):
        for label in ('layer_2_thickness(nm)', 'layer_2_thickness', 'layer_3_thickness(A)'):
            with self.subTest(label=label):
                data = rewrite_workbook(workbook(sheets=2),
                    lambda name, value: value.replace(b'1#M_0@Einf', label.encode())
                    if name == 'xl/worksheets/sheet2.xml' else value)
                result = parse_file(data, 'multilayer.xlsx')
                self.assertEqual(result['blocks'], [])
                self.assertEqual(result['status'], 'original_only')
                self.assertIn('unverified_multilayer', {i['code'] for i in result['blocking_issues']})

    def test_formula_caches_preserve_lexeme_type_presence_and_block(self):
        cases = [('n', b'<v>1.234567890123456789e+01</v>', '1.234567890123456789e+01', True),
                 ('n', b'', None, False), ('n', b'<v/>', None, True),
                 ('n', b'<v>NaN</v>', 'NaN', True),
                 ('n', b'<v>bad</v>', 'bad', True),
                 ('e', b'<v>#DIV/0!</v>', '#DIV/0!', True),
                 ('str', b'<v>untrusted</v>', 'untrusted', True)]
        for cache_type, cache, lexeme, present in cases:
            with self.subTest(cache_type=cache_type, cache=cache):
                replacement = b'<c r="F3" t="' + cache_type.encode() + b'"><f>1+1</f>' + cache + b'</c>'
                data = rewrite_sheet(workbook(), lambda b: re.sub(rb'<c r="F3".*?</c>', replacement, b))
                result = parse_file(data, 'formula.xlsx')
                point = result['blocks'][0]['points'][0]
                raw = point['raw_values'][5]
                self.assertEqual(raw['value'], '=1+1')
                self.assertEqual(raw['formula'], '=1+1')
                self.assertEqual(raw['cached_value_lexeme'], lexeme)
                self.assertEqual(raw['cached_type'], cache_type)
                self.assertEqual(raw['cache_present'], present)
                self.assertIsNone(point['thickness_nm'])
                self.assertEqual(result['status'], 'needs_confirmation')
                self.assertIn('untrusted_formula', {i['code'] for i in result['blocking_issues']})
                json.dumps(result, allow_nan=False)

    def test_formula_in_preamble_is_also_blocking(self):
        data = rewrite_sheet(workbook(), lambda b: b.replace(b'</row>',
                             b'<c r="C1"><f>1+1</f><v>2</v></c></row>', 1))
        result = parse_file(data, 'formula.xlsx')
        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertEqual(result['blocks'][0]['metadata']['preamble'][0][-1]['cached_value_lexeme'], '2')

    def test_zip_expansion_output_and_xml_complexity_preflight(self):
        for constant, limit, code in [('MAX_EXPANDED', 1000, 'expanded_size_limit'),
                                     ('MAX_OUTPUT_BYTES', 2000, 'output_size_limit'),
                                     ('MAX_XML_NODES', 10, 'xml_complexity_limit'),
                                     ('MAX_XML_DEPTH', 3, 'xml_complexity_limit'),
                                     ('MAX_CELL_TEXT', 5, 'cell_text_limit')]:
            with self.subTest(constant=constant), patch.object(core, constant, limit):
                self.assert_preflight_rejected(workbook(), code)
        # Verify actual byte accounting independently from the ZIP directory sizes.
        with patch.object(core, 'MAX_EXPANDED', 4):
            with self.assertRaises(core.PreviewLimit):
                core._ExpandedReader(io.BytesIO(b'12345'), [0]).read(5)

    def test_shared_string_expansion_checked_before_openpyxl(self):
        data = workbook()
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
            for name in source.namelist():
                value = source.read(name)
                if name.startswith('xl/worksheets/'):
                    value = re.sub(rb'<c r="F3".*?</c>', b'<c r="F3" t="s"><v>0</v></c>', value)
                target.writestr(name, value)
            target.writestr('xl/sharedStrings.xml',
                            b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                            b'<si><t>' + b'x' * 8000 + b'</t></si></sst>')
        with patch.object(core, 'MAX_OUTPUT_BYTES', 90000):
            self.assert_preflight_rejected(output.getvalue(), 'output_size_limit')

    def test_output_limit_clears_partial_blocks(self):
        data = workbook(sheets=2)
        original = core._json_size
        def measured(value):
            if isinstance(value, dict) and value.get('point_no') == 1:
                raise core.PreviewLimit('output_size_limit', 'test cumulative output limit')
            return original(value)
        with patch.object(core, '_json_size', side_effect=measured):
            result = parse_file(data, 'x.xlsx')
        self.assertEqual(result['blocks'], [])
        self.assertEqual(result['status'], 'original_only')
        self.assertIn('output_size_limit', {i['code'] for i in result['blocking_issues']})

    @unittest.skipUnless(os.getenv('ALE_PARSER_UPLOADS'), 'Real ZIP corpus path not configured')
    def test_all_unique_real_workbooks_and_xps(self):
        from openpyxl import load_workbook
        seen = set(); counts = {}; eoptics = 0; points = 0; shapes = set()
        uploads = Path(os.environ['ALE_PARSER_UPLOADS'])
        archives = sorted(p for p in uploads.glob('*.zip') if not p.name.startswith('第三'))
        self.assertEqual(len(archives), 4)
        for archive in archives:
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    ext = Path(info.filename).suffix.lower()
                    if ext not in ('.xlsx', '.xml', '.vgd', '.xls'): continue
                    content = z.read(info); sha = hashlib.sha256(content).hexdigest()
                    if sha in seen: continue
                    seen.add(sha)
                    r = parse_file(content, info.filename)
                    json.dumps(r, allow_nan=False)
                    counts[r['type']] = counts.get(r['type'], 0)+1
                    self.assertFalse(any(i['code'] == 'invalid_file' for i in r['blocking_issues']), info.filename)
                    if r['type'] == 'eoptics':
                        eoptics += 1
                        w = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
                        expected = 0
                        for sheet in w:
                            sheet.reset_dimensions()
                            rows = list(sheet.values)
                            headers = [i for i, row in enumerate(rows) if 'No' in row and 'layer_1_thickness(nm)' in row]
                            for hi in headers:
                                shapes.add(len(rows[hi]))
                                from app.parsers.core import SUMMARY
                                expected += sum(1 for row in rows[hi+1:] if any(v is not None for v in row) and str(row[rows[hi].index('No')]).strip() not in SUMMARY)
                        w.close()
                        actual = sum(len(b['points']) for b in r['blocks']); points += actual
                        self.assertEqual(actual, expected, info.filename)
                        # Independent XML oracle checks every point field and every raw
                        # cell, not just totals from the same read_only dimension path.
                        with zipfile.ZipFile(io.BytesIO(content)) as parts:
                            xml_cells = {}
                            from defusedxml import ElementTree as SafeET
                            for name in parts.namelist():
                                if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                                    root = SafeET.fromstring(parts.read(name))
                                    xml_cells[name] = {c.get('r'): c for c in root.iter(core.NS+'c')}
                            check_wb = load_workbook(io.BytesIO(content), read_only=True)
                            paths = {sheet.title: sheet._worksheet_path.lstrip('/') for sheet in check_wb}
                            check_wb.close()
                            for block in r['blocks']:
                                cells = xml_cells[paths[block['locator']['sheet']]]
                                labels = block['metadata']['headers']
                                for point in block['points']:
                                    self.assertEqual(point['source_row'], point['locator']['row'])
                                    for index, raw in enumerate(point['raw_values']):
                                        cell = cells.get(raw['cell'])
                                        if cell is None:
                                            self.assertIsNone(raw['value'])
                                            continue
                                        value = cell.find(core.NS+'v')
                                        formula = cell.find(core.NS+'f')
                                        if formula is not None:
                                            self.assertEqual(raw['formula'], '=' + (formula.text or ''))
                                            self.assertEqual(raw['cached_value_lexeme'], value.text if value is not None else None)
                                            self.assertEqual(raw['cache_present'], value is not None)
                                            self.assertEqual(raw['cached_type'], cell.get('t', 'n'))
                                            self.assertEqual(r['status'], 'needs_confirmation')
                                            continue
                                        if cell.get('t', 'n') == 'n' and value is not None:
                                            self.assertEqual(raw['value'], value.text, (info.filename, raw['cell']))
                                            field = core.FIELDS.get(labels[index])
                                            if field and field not in ('aoi_deg', 'lbh'):
                                                self.assertEqual(Decimal(str(point[field])), Decimal(value.text),
                                                                 (info.filename, raw['cell'], field))
                                            if labels[index] in point['dispersion_params']:
                                                self.assertEqual(Decimal(point['dispersion_params'][labels[index]]),
                                                                 Decimal(value.text))
                                    thickness_column = labels.index('layer_1_thickness(nm)') + 1
                                    from openpyxl.utils import get_column_letter
                                    self.assertEqual(point['source_cell'],
                                                     f'{get_column_letter(thickness_column)}{point["source_row"]}')
                        self.assertTrue(all(b['metadata']['optical_model']['parameter_columns'] for b in r['blocks']))
                        print('REAL_EOPTICS', sha, actual, r['status'], info.filename)
                    else:
                        self.assertEqual(r['blocks'], [])
                        if ext == '.xml':
                            self.assertEqual(r['type'], 'xps_chart_configuration')
                            print('REAL_XPS_XML', sha, r['preview_metadata'])
        self.assertEqual(eoptics, 130)
        self.assertEqual(points, 987)
        self.assertEqual(shapes, {20, 23, 29, 38, 41})
        print('REAL_CORPUS_RESULT', {'unique_eoptics': eoptics, 'points': points, 'column_variants': sorted(shapes), 'types': counts})


if __name__ == '__main__':
    unittest.main(verbosity=2)
