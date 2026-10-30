"""Per-widget rendering with actual client transitions and fake boundaries."""
import ast
import hashlib
from copy import deepcopy
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from ast_preservation import preservation_dump
from desktop_gui_support.intent_lineage import restore_predecessor

from adaptive_inference.desktop import control_client as cc
from test_desktop_control_client import Root, Widget, FakeWorker, Binding, bootstrap, status

HERE=Path(__file__).resolve().parent
RENDER_OPTIONS=13  # Five text labels, seven task/service buttons, one footer.

def presentation():
    return {'objective':'Preserve the original task.', 'connection':'Connected.',
            'task':'Task is in progress.', 'waiting':'Waiting for resources.', 'action':'',
            'buttons':{'pause':True,'resume':True,'cancel':True,'stop':True,'continue':False,'retry':False,'new_task':False},
            'closing':False,'cleanup_unconfirmed':False}


class RenderTests(unittest.TestCase):
    def setUp(self):
        calls=self.calls=[]
        class CountingWidget(Widget):
            fail_before=False
            fail_after=False
            def configure(self,**kwargs):
                calls.append((self,dict(kwargs)))
                if self.fail_before:raise RuntimeError('injected before widget update')
                super().configure(**kwargs)
                if self.fail_after:raise RuntimeError('injected after widget update')
        self.root=Root()
        self.view=cc.TkView(self.root,ttk_module=SimpleNamespace(
            Frame=CountingWidget,Label=CountingWidget,Button=CountingWidget))
        self.assertEqual(set(self.view.buttons),{'pause','resume','continue','cancel','stop','retry','new_task'})

    def test_repeated_equal_presentations_make_no_additional_widget_calls(self):
        state=presentation();self.view.render(state)
        self.assertEqual(len(self.calls),RENDER_OPTIONS)
        for _ in range(1000):self.view.render(deepcopy(state))
        self.assertEqual(len(self.calls),RENDER_OPTIONS)
        self.assertEqual(self.view.labels['objective'].options['text'],state['objective'])

    def test_only_changed_text_button_and_cleanup_are_configured(self):
        state=presentation();self.view.render(state);self.calls.clear()
        updated=deepcopy(state)
        updated.update(action='Pause applied.',cleanup_unconfirmed=True)
        updated['buttons']['resume']=False
        self.view.render(updated)
        self.assertEqual(self.calls,[(self.view.labels['action'],{'text':'Pause applied.'}),
            (self.view.buttons['resume'],{'state':'disabled'}),
            (self.view.footnote,{'text':'Window cleanup is unconfirmed.'})])
        self.assertEqual(self.view.labels['action'].options['text'],'Pause applied.')
        self.assertEqual(self.view.buttons['resume'].options['state'],'disabled')
        self.assertEqual(self.view.footnote.options['text'],'Window cleanup is unconfirmed.')

    def test_caller_mutation_cannot_mutate_saved_option_values(self):
        state=presentation();self.view.render(state);self.calls.clear()
        state['buttons']['pause']=False;state['waiting']='Task paused.'
        self.view.render(state)
        self.assertEqual(self.calls,[(self.view.labels['waiting'],{'text':'Task paused.'}),
            (self.view.buttons['pause'],{'state':'disabled'})])

    def test_first_render_failure_retries_only_unsuccessful_option(self):
        state=presentation();self.view.footnote.fail_before=True
        with self.assertRaisesRegex(RuntimeError,'before'):self.view.render(state)
        self.assertEqual(len(self.view._rendered_options),RENDER_OPTIONS-1)
        self.assertNotIn((self.view.footnote,'text'),self.view._rendered_options)
        self.view.footnote.fail_before=False;self.calls.clear()
        self.view.render(state)
        self.assertEqual(self.calls,[(self.view.footnote,{'text':
            'Closing this window leaves the task and engine running.'})])
        self.assertEqual(len(self.view._rendered_options),RENDER_OPTIONS)

    def test_apply_then_raise_invalidates_failed_option_and_old_value_is_repaired(self):
        old=presentation();self.view.render(old)
        changed=deepcopy(old);changed['action']='Partially applied new action.'
        widget=self.view.labels['action'];widget.fail_after=True
        with self.assertRaisesRegex(RuntimeError,'after'):self.view.render(changed)
        self.assertEqual(widget.options['text'],changed['action'])
        self.assertNotIn((widget,'text'),self.view._rendered_options)
        widget.fail_after=False;self.calls.clear();self.view.render(old)
        self.assertEqual(self.calls,[(widget,{'text':old['action']})])
        self.assertEqual(widget.options['text'],old['action'])

    def test_successful_changed_peer_is_retained_when_later_option_fails(self):
        state=presentation();self.view.render(state)
        changed=deepcopy(state);changed['waiting']='New waiting text.';changed['action']='New action.'
        widget=self.view.labels['action'];widget.fail_after=True
        with self.assertRaises(RuntimeError):self.view.render(changed)
        self.assertEqual(self.view._rendered_options[(self.view.labels['waiting'],'text')],changed['waiting'])
        widget.fail_after=False;self.calls.clear();self.view.render(changed)
        self.assertEqual(self.calls,[(widget,{'text':changed['action']})])
        self.assertEqual(widget.options['text'],changed['action'])

    def test_unattempted_changed_options_remain_pending_after_failure(self):
        old=presentation();self.view.render(old)
        changed=deepcopy(old);changed['objective']='Changed objective.';changed['waiting']='Changed waiting.'
        failed=self.view.labels['objective'];failed.fail_before=True
        with self.assertRaises(RuntimeError):self.view.render(changed)
        self.assertEqual(self.view.labels['waiting'].options['text'],old['waiting'])
        failed.fail_before=False;self.calls.clear();self.view.render(changed)
        self.assertEqual(self.calls,[(failed,{'text':changed['objective']}),
            (self.view.labels['waiting'],{'text':changed['waiting']})])

    def test_waiting_text_change_never_reconfigures_unchanged_objective(self):
        state=presentation();self.view.render(state);self.calls.clear()
        state['waiting']='Current progress is not yet known.';self.view.render(state)
        self.assertEqual(self.calls,[(self.view.labels['waiting'],{'text':state['waiting']})])

    def test_nonvisual_closing_field_alone_does_not_configure_widgets(self):
        state=presentation();self.view.render(state);self.calls.clear()
        state['closing']=True;self.view.render(state)
        self.assertEqual(self.calls,[])

    def test_unchanged_state_still_checks_owner_thread(self):
        state=presentation();self.view.render(state);errors=[]
        def elsewhere():
            try:self.view.render(state)
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=elsewhere,daemon=False)
        thread.start();thread.join(timeout=2)
        self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],PermissionError)
        self.assertEqual(len(self.calls),RENDER_OPTIONS)

    def test_tick_poll_and_close_callbacks_continue_on_equal_presentations(self):
        events=[];state=presentation()
        controller=SimpleNamespace(closed=False,
            tick=lambda:(events.append('tick'),self.view.render(state)),
            poll_status=lambda:events.append('poll'),close=lambda:events.append('close'))
        self.view.attach(controller)
        for _ in range(20):self.view._tick()
        self.view._poll();self.root.protocols['WM_DELETE_WINDOW']()
        self.assertEqual(events,['tick']*20+['poll','close'])
        self.assertEqual(len(self.calls),RENDER_OPTIONS)
        self.assertEqual([n for n,_ in self.root.calls],[100,1000]+[100]*20+[1000])

    def ready_client(self):
        worker=FakeWorker()
        client=cc.ClientController(bootstrap(),worker,Binding(),self.view)
        self.view.attach(client);client.start()
        worker.respond({'ok':True,'state':'window_ready'});client.tick()
        client.poll_status();worker.respond(status());client.tick()
        return client,worker

    def test_actual_client_status_poll_never_disables_eligible_buttons_or_redraws(self):
        client,worker=self.ready_client();objective=self.view.labels['objective']
        self.assertEqual(sum(widget is objective for widget,_ in self.calls),1)
        self.calls.clear();sent=len(worker.sent)
        self.assertTrue(client.poll_status());request=client.pending
        self.assertEqual(request.method,'status');client.tick()
        self.assertEqual(self.calls,[])
        self.assertIs(client.pending,request)
        self.assertTrue(all(client.buttons()[name] for name in ('pause','resume','cancel','stop')))
        self.calls.clear();client.tick();self.assertEqual(self.calls,[])
        worker.respond(status());client.tick()
        self.assertEqual(self.calls,[])
        self.assertIsNone(client.pending);self.assertEqual(len(worker.sent),sent+1)
        self.assertEqual(self.view.labels['objective'].options['text'],bootstrap().objective)

    def test_actual_client_reply_before_tick_needs_no_widget_updates(self):
        client,worker=self.ready_client();self.calls.clear()
        client.poll_status();worker.respond(status());client.tick()
        self.assertEqual(self.calls,[]);self.assertIsNone(client.pending)


class PreservationTests(unittest.TestCase):
    def test_module_except_view_cache_terminal_presentation_and_copy_import_is_ast_exact(self):
        def normalized(path,predecessor):
            tree=ast.parse(path.read_text())
            if not predecessor:tree=restore_predecessor(tree)
            if predecessor:
                copies=[node for node in tree.body if isinstance(node,ast.ImportFrom) and node.module=='copy']
                self.assertEqual(len(copies),1)
                self.assertEqual([(n.name,n.asname) for n in copies[0].names],[('deepcopy',None)])
                tree.body.remove(copies[0])
            for node in tree.body:
                if isinstance(node,ast.ClassDef) and node.name=='ClientController':
                    for item in node.body:
                        if isinstance(item,ast.FunctionDef) and item.name=='render':
                            item.body=[ast.Pass()]
                if isinstance(node,ast.ClassDef) and node.name=='TkView':
                    node.body=[item for item in node.body if not (
                        isinstance(item,ast.FunctionDef) and item.name=='_minimize')]
                    for item in node.body:
                        if isinstance(item,ast.FunctionDef) and item.name in ('__init__','render','attach'):
                            item.body=[ast.Pass()]
                            for index in reversed(range(len(item.args.kwonlyargs))):
                                if item.args.kwonlyargs[index].arg=='minimize_on_close':
                                    del item.args.kwonlyargs[index];del item.args.kw_defaults[index]
            return preservation_dump(tree)
        self.assertEqual(hashlib.sha256(normalized(Path(cc.__file__),False).encode()).hexdigest(),
                         'e832cd7511bfa41c75f89917cecc7241d7bb922bfc4441f26207a29d4c2eff5c')


if __name__=='__main__':unittest.main(verbosity=2)
