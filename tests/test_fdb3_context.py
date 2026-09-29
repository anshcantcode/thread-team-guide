from copy import deepcopy
import unittest
from thread_agent.fdb3 import planner_view


class PlannerContextTests(unittest.TestCase):
    def test_old_transcript_is_bounded_without_losing_constraints_or_unknown_effects(self):
        context={'messages':[{'message_index':i,'payload':{'text':f'old discussion {i}'}} for i in range(100)],
            'current_turn_start':99,'state':{'intent':'travel','slots':{'date':'2031-06-07','budget':430}},
            'actions':[{'call_id':'effect-17','status':'unknown','args':{'person':'Iona'},'revision':2}],
            'tool_results':[]}
        original=deepcopy(context)
        view=planner_view(context)
        self.assertEqual(len(view['messages']),5)
        self.assertEqual(view['messages'][-1]['message_index'],99)
        self.assertEqual(view['current_turn_start'],99)
        self.assertEqual(view['state'],context['state'])
        self.assertEqual(view['actions'],context['actions'])
        self.assertEqual(context,original)

    def test_all_current_chunks_and_their_authority_indices_survive(self):
        context={'messages':[{'message_index':i,'payload':{'text':str(i)}} for i in range(30)],
                 'current_turn_start':7}
        view=planner_view(context)
        self.assertEqual([m['message_index'] for m in view['messages']],list(range(3,30)))
        self.assertEqual(view['current_turn_start'],7)

    def test_initial_request_is_not_compacted(self):
        context={'messages':[{'message_index':0,'payload':{'text':'Hello'}}],'current_turn_start':0}
        self.assertEqual(planner_view(context),context)
