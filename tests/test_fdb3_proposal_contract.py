"""Independent JSON Schema implementation checks the native generation contract.

Schema acceptance is not authority: existing controller regressions separately
reject invented quotes, stale grants, tool-result instructions and wrong values.
"""
from copy import deepcopy
import unittest
from jsonschema import Draft202012Validator
from thread_agent.fdb3 import proposal_schema


TOOLS={'inspect_crate':{'kind':'read_only'}, 'mark_crate':{'kind':'state_modifying'}}


class ProposalContractTests(unittest.TestCase):
    def setUp(self):
        schema=proposal_schema(TOOLS)
        Draft202012Validator.check_schema(schema)
        self.validator=Draft202012Validator(schema)
        self.read={'api_name':'inspect_crate','args':{'crate':'Kestrel'},'response_template':'Crate {label}.'}
        self.write={'api_name':'mark_crate','args':{'crate':'Kestrel'},'response_template':'Mark {receipt}.',
                    'authorization':{'quote':'Mark crate Kestrel','message_index':2}}

    def accepted(self,step):
        return self.validator.is_valid({'intent':'crates','slots':{},'tool_calls':[step]})

    def test_reads_need_no_grant_but_every_write_requires_a_nonempty_quote(self):
        self.assertTrue(self.accepted(self.read))
        self.assertTrue(self.accepted(self.write))
        for authorization in (None,{}, {'quote':''}, {'quote':'yes'}, {'quote':'Mark crate Kestrel','message_index':True}):
            step=deepcopy(self.write);step['authorization']=authorization
            self.assertFalse(self.accepted(step))
        step=deepcopy(self.write);del step['authorization']
        self.assertFalse(self.accepted(step))

    def test_nested_continuation_cannot_evade_required_write_evidence(self):
        read=deepcopy(self.read);write=deepcopy(self.write);del write['authorization']
        read['after_result']=write
        self.assertFalse(self.accepted(read))
        read['after_result']=self.write
        self.assertTrue(self.accepted(read))

    def test_only_declared_names_and_known_step_shapes_can_be_generated(self):
        for key,value in [('api_name','invented_tool'),('args','Kestrel'),('after_result',False),('select',None)]:
            step=deepcopy(self.read);step[key]=value
            self.assertFalse(self.accepted(step))
        step=deepcopy(self.read);step['authorization']=self.write['authorization']
        self.assertFalse(self.accepted(step))

    def test_result_binding_and_explicit_retention_remain_expressible(self):
        read={**self.read,'retain_call_id':'read-older'}
        self.assertTrue(self.accepted(read))
        write=deepcopy(self.write)
        write['result_bindings']={'crate':{'call_id':'read-older','path':'id'}}
        self.assertTrue(self.accepted(write))

    def test_retention_can_only_name_a_retainable_in_flight_read(self):
        # Public runs generated "retain_call_id": "null" and clause IDs such as "5.4"; a
        # free string let a local model block its own plan.
        for retainable, value, valid in (([], 'null', False), ([], '5.4', False), (['call-3'], 'call-3', True),
                                         (['call-3'], 'null', False), (['call-3'], 'call-4', False)):
            validator = Draft202012Validator(proposal_schema(TOOLS, retain_call_ids=retainable))
            with self.subTest(retainable=retainable, value=value):
                self.assertEqual(validator.is_valid({'intent': 'crates', 'slots': {}, 'tool_calls': [
                    {**self.read, 'retain_call_id': value}]}), valid)
                self.assertTrue(validator.is_valid({'intent': 'crates', 'slots': {}, 'tool_calls': [self.read]}))

    def test_no_tool_manifest_only_allows_an_empty_call_list(self):
        validator=Draft202012Validator(proposal_schema({}))
        self.assertTrue(validator.is_valid({'intent':'reply','slots':{},'tool_calls':[]}))
        self.assertFalse(validator.is_valid({'intent':'reply','slots':{},'tool_calls':[self.read]}))

    def test_declared_arguments_are_typed_per_tool(self):
        tools = {'track_order': {'kind': 'read_only', 'args': {'order_id': {'type': 'string', 'required': True}}},
                 'add_to_cart': {'kind': 'state_modifying', 'args': {
                     'product_id': {'type': 'string', 'required': True},
                     'quantity': {'type': 'integer', 'required': False, 'default': 1}}}}
        schema = proposal_schema(tools, clause_ids=['4.0', '5.2'])
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        def valid(step): return validator.is_valid({'intent': 'x', 'slots': {}, 'tool_calls': [step]})
        write = {'api_name': 'add_to_cart', 'args': {'product_id': 'J9', 'quantity': 1},
                 'response_template': 'Added.', 'authorization': {'clauses': ['4.0', '5.2']}}
        self.assertTrue(valid(write))
        for args in ({'product_id': 'J9', 'quantity': '1'}, {'product_id': 'J9', 'qty': 1}, {'order_id': 'J9'}):
            with self.subTest(args=args):
                self.assertFalse(valid({**write, 'args': args}))
        for authorization in ({'clauses': ['9.9']}, {'clauses': []}, {'quote': 'Add J9'}, {'clauses': ['4.0'], 'quote': 'x'}):
            with self.subTest(authorization=authorization):
                self.assertFalse(valid({**write, 'authorization': authorization}))
        # Arguments of another tool cannot be borrowed, and binding keys are declared names.
        self.assertFalse(valid({'api_name': 'track_order', 'args': {'product_id': 'J9'}, 'response_template': 'x'}))
        bound = {**write, 'args': {'quantity': 1}, 'result_bindings': {'product_id': {'call_id': 'call-1', 'path': 'products.0.product_id'}}}
        self.assertTrue(valid(bound))
        self.assertFalse(valid({**bound, 'result_bindings': {'sku': {'call_id': 'call-1', 'path': 'x'}}}))

    def test_selection_and_bindings_only_on_result_continuations(self):
        tools = {'find_items': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}},
                 'hold_item': {'kind': 'state_modifying', 'args': {'item_id': {'type': 'string'}}}}
        validator = Draft202012Validator(proposal_schema(tools, clause_ids=['0.0']))
        def valid(step): return validator.is_valid({'intent': 'x', 'slots': {}, 'tool_calls': [step]})
        read = {'api_name': 'find_items', 'args': {'query': 'kettle'}, 'response_template': ''}
        hold = {'api_name': 'hold_item', 'args': {}, 'response_template': 'Held {item_id}.',
                'authorization': {'clauses': ['0.0']}, 'select': {'path': 'items', 'where': {'name': 'kettle'}},
                'bindings': {'item_id': 'id'}}
        self.assertTrue(valid({**read, 'after_result': hold}))
        self.assertFalse(valid({**read, 'select': {'path': 'items', 'where': {'name': 'kettle'}}}))
        self.assertFalse(valid({**read, 'bindings': {'query': 'id'}}))

    def test_chain_depth_is_bounded_like_the_controller(self):
        # 100-run 20260926T200433Z case 1: an unbounded after_result chain exhausted the context.
        tools = {'track_order': {'kind': 'read_only', 'args': {'order_id': {'type': 'string'}}}}
        validator = Draft202012Validator(proposal_schema(tools, clause_ids=['0.0']))
        def chain(depth):
            step = {'api_name': 'track_order', 'args': {'order_id': str(depth)}, 'response_template': 'x'}
            for level in range(depth):
                step = {'api_name': 'track_order', 'args': {'order_id': str(level)}, 'response_template': '',
                        'after_result': step}
            return {'intent': 'x', 'slots': {}, 'tool_calls': [step]}
        self.assertTrue(validator.is_valid(chain(3)))
        self.assertFalse(validator.is_valid(chain(4)))

    def test_citations_use_current_original_indices_or_omit_for_spanning_quotes(self):
        validator=Draft202012Validator(proposal_schema(TOOLS,[7,9]))
        step=deepcopy(self.write)
        def valid(): return validator.is_valid({'intent':'crates','slots':{},'tool_calls':[step]})
        for index in (0,2,8):
            step['authorization']['message_index']=index
            self.assertFalse(valid())
        step['authorization']['message_index']=9
        self.assertTrue(valid())
        del step['authorization']['message_index']
        self.assertTrue(valid())
