"""Bounded parent-owned process layout. Steps remain the scientific source of truth."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

Name = Annotated[str, Field(min_length=1, max_length=128)]
Reference = Annotated[int, Field(strict=True, gt=0)] | Annotated[str, Field(min_length=1, max_length=80)]
Repeat = Annotated[int, Field(strict=True, ge=0, le=1000000)] | None

class FlowNode(Input):
    kind: Literal['group', 'step']
    id: Annotated[str, Field(min_length=1, max_length=80)]
    name: Name | None = None
    repeat: Repeat = None
    step_id: Reference | None = None
    children: Annotated[list['FlowNode'], Field(max_length=500)] = Field(default_factory=list)

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'step' and (self.step_id is None or self.children or self.name is not None or self.repeat is not None):
            raise ValueError('A step node contains only its ID and step reference')
        if self.kind == 'group' and (self.step_id is not None or not self.name):
            raise ValueError('A group needs a name and cannot contain a step reference')
        return self

class ProcessFlow(Input):
    version: Literal[1] = 1
    total_cycles: Repeat = None
    children: Annotated[list[FlowNode], Field(max_length=500)] = Field(default_factory=list)

    @model_validator(mode='after')
    def bounded_tree(self):
        ids, refs = set(), set()
        count = groups = 0
        def visit(nodes, depth):
            nonlocal count, groups
            if depth > 5: raise ValueError('At most four nested groups are supported')
            for node in nodes:
                count += 1
                if count > 500: raise ValueError('At most 500 flow nodes are supported')
                if node.id in ids: raise ValueError('Flow node IDs must be unique')
                ids.add(node.id)
                if node.kind == 'step':
                    if node.step_id in refs: raise ValueError('Each step may appear only once; use an explicit group repeat')
                    refs.add(node.step_id)
                else:
                    groups += 1
                    if groups > 32: raise ValueError('At most 32 groups are supported')
                    visit(node.children, depth + 1)
        visit(self.children, 1)
        return self

def references(flow):
    result=[]
    def visit(nodes):
        for node in nodes:
            if node['kind']=='step': result.append(node['step_id'])
            else: visit(node['children'])
    visit(flow['children'])
    return result

def resolve(flow, mapping):
    def visit(nodes):
        for node in nodes:
            if node['kind']=='step': node['step_id']=mapping[node['step_id']]
            else: visit(node['children'])
    visit(flow['children'])
    return flow
