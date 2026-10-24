"""CPU-only sanitizer gates; no SDK, model, network or source changes."""
import copy
import ast
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch
from contextlib import closing, redirect_stderr

import sanitize_milestone_v7 as s


class SanitizerTests(unittest.TestCase):
    def test_json_duplicate_and_nonfinite_refused(self):
        for text in ('{"passed":true,"passed":false}', '{"n":NaN}'):
            with self.assertRaises(s.Refused):s.parse(text)

    def test_type_sensitive_quality_and_usage(self):
        with self.assertRaises(s.Refused):s.exact(True,1,'bool_is_not_count')
        good={'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,
              'secret':'do not copy','prompt_tokens_details':{'cached_tokens':2,'private':'secret'}}
        self.assertEqual(s.usage(good),{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,
                                      'prompt_tokens_details':{'cached_tokens':2}})
        for changes in ({'total_tokens':111},{'completion_tokens':10924,'total_tokens':11024},
                        {'prompt_tokens':60000,'total_tokens':60010}):
            with self.assertRaises(s.Refused):s.usage({**good,**changes})

    @staticmethod
    def inference():
        return [{'index':i,'model':s.MODEL,'quality':s.QUALITY,'answer':s.ARITHMETIC,
                 'finish_reason':'stop','requested_at':i*10,'completed_at':i*10+5,
                 'request_class':'background','gateway_class':'background',
                 'request_sha256':'a'*64,'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110},
                 'reasoning_content':'PRIVATE_REASONING_SENTINEL','path':r'C:\Private\secret'} for i in range(2)]

    def test_inference_explicit_allowlist_and_arithmetic(self):
        rows=self.inference();safe=s.inference(rows)
        self.assertEqual(safe[0]['elapsed_s'],5)
        self.assertNotIn('PRIVATE',json.dumps(safe));s.privacy_check(s.encoded(safe))
        rows[1]['answer']={**s.ARITHMETIC,'units':18}
        with self.assertRaises(s.Refused):s.inference(rows)

    def test_missing_or_failed_second_request_refused(self):
        rows=self.inference()
        with self.assertRaises(s.Refused):s.inference(rows[:1])
        rows[1]['finish_reason']='length'
        with self.assertRaises(s.Refused):s.inference(rows)

    def test_native_release_requires_matching_all_exit_counts(self):
        row={'owner_id':'a'*32,'released':True,'cleanup_confirmed':True,'port_free':True,
             'retained_processes':7,'confirmed_process_exits':7,'server_exit_code':0,
             'identity':{'exe':r'C:\Private\python.exe'},
             'retained_at_stop':[{'exited':True,'exe':r'C:\Private\native.exe'}]}
        safe=s.release(row);self.assertNotIn('identity',safe);s.privacy_check(s.encoded(safe))
        for changes in ({'port_free':False},{'confirmed_process_exits':6},{'server_exit_code':1},
                        {'retained_at_stop':[{'exited':False}]}):
            with self.assertRaises(s.Refused):s.release({**row,**changes})

    def test_compare_preserves_no_improvement(self):
        summaries=[{'valid_foreground_run':True,'paint_interval_p95_ms':x,
                    'stalls_over_50ms_fraction':0} for x in (17.35,17.78,17.64)]
        receipt={'valid_comparison':True,'controlled_p95_limit_ms':25,
                 'controlled_responsiveness_passed':True,'uncontrolled_degradation_detected':False,
                 'improvement_observed':False}
        self.assertFalse(s.comparison(receipt,summaries)['improvement_observed'])
        with self.assertRaises(s.Refused):s.comparison({**receipt,'improvement_observed':True},summaries)
        with self.assertRaises(s.Refused):s.comparison({**receipt,'controlled_responsiveness_passed':False},summaries)

    def test_tool_completion_is_preserved_without_unknown_fields(self):
        row={'at':1,'tool_completed':'a'*32,'interrupted':False,'private':'SECRET'}
        self.assertEqual(s.handoff_events([row]),[{k:row[k] for k in ('at','tool_completed','interrupted')}])
        with self.assertRaises(s.Refused):s.handoff_events([{'at':1,'new_unknown_event':True}])

    def test_video_pass_still_requires_three_actual_zero_exits(self):
        class Inputs:
            def read(self,*args):return row
        row={'passed':True,'probe':s.PROBE,'owned_process_exit_codes':[0,0,1]}
        with self.assertRaisesRegex(s.Refused,'video_three_zero_exits'):
            s.video(Inputs(),Path('.'),row)

    def test_recovery_pass_does_not_override_changed_effects(self):
        class Inputs:
            def read(self,*args):return {'passed':True,'effect_receipts_unchanged':False}
        with self.assertRaisesRegex(s.Refused,'effect_receipts_changed'):
            s.recovery(Inputs(),Path('.'),Path('.'))

    def test_privacy_guard_paths_and_raw_message_fields(self):
        for value in ({'path':r'C:\Private\x'}, {'x':'/home/user/x'}, {'messages':[]},
                      {'reasoning_content':'secret'},{'exe':'python.exe'}):
            with self.assertRaises(s.Refused):s.privacy_check(s.encoded(value))

    def test_input_change_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'receipt.json';p.write_text('{"passed":true}')
            reader=s.Inputs(root);reader.read('receipt',p);p.write_text('{"passed":false}')
            with self.assertRaisesRegex(s.Refused,'input_changed'):reader.unchanged()

    def test_missing_terminal_no_output_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'new-output';comparison=root/'comparison.json'
            comparison.write_text('{}')
            with redirect_stderr(io.StringIO()):
                code=s.main(['--root',str(root),'--comparison',str(comparison),'--output',str(output)])
            self.assertEqual(code,2);self.assertFalse(output.exists())
            output.mkdir();sentinel=output/'preserve.txt';sentinel.write_text('existing')
            with redirect_stderr(io.StringIO()):
                code=s.main(['--root',str(root),'--comparison',str(comparison),'--output',str(output)])
            self.assertEqual(code,2);self.assertEqual(sentinel.read_text(),'existing')

    def test_encoding_is_deterministic(self):
        self.assertEqual(s.encoded({'z':2,'a':1}),s.encoded({'a':1,'z':2}))


class SuccessorWaitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.controlled=self.root/'controlled-11';self.controlled.mkdir()
        self.phase_events=[{'at':90.,'kind':'hermes_phase','phase':'before_restart'},
                           {'at':200.,'kind':'hermes_process_restart','safe_boundary':True}]
        self.flush_events()
        self.ui=self.controlled/'hermes-foreground';self.ui.mkdir()
        self.hermes=self.root/'hermes-real-03';self.hermes.mkdir()
        self.ready={'pid':123,'started_monotonic_s':100.}
        self.result={'pid':123,'valid_foreground_run':True}
        self.write(self.ui/'ready.json',self.ready)
        self.write(self.ui/'result.json',self.result)
        self.write(self.hermes/'controller-ready.json',{'ready':True,'model':s.MODEL,
            'quality':s.QUALITY,'gateway_instance':'a'*32})
        self.write(self.hermes/'wire-observations.json',[{'body_sha256':'b'*64}])
        self.write(self.hermes/'result-222.json',{'admission_attempts':1,'admission_deferrals':0})
        self.state={'deadline_monotonic':900.,'admission_attempts':1,'admission_deferrals':[], 'requests':1}
        self.before={'deadline_monotonic':900.}
        self.history={'state':{'phase':'waiting_admission','status':'pending',
            'pending_request':{'model':s.MODEL},'deadline_monotonic':900.},
            'operation':None,'requires_reconciliation':False}
        with closing(sqlite3.connect(self.hermes/'task.sqlite3')) as db, db:
            db.execute('CREATE TABLE history(task_id TEXT,revision INTEGER,payload TEXT)')
            db.execute('INSERT INTO history VALUES (?,?,?)',('orders-report',4,json.dumps(self.history)))
        self.row={'deadline_monotonic':900.,'gateway_instance':'a'*32,'agent_foreground':self.result,
            'agent_foreground_process':{'pid':123,'same_active_ticket_at_ready':True,
                'active_class_at_ready':'normal','active_sequence_at_ready':2,
                'observed_at_monotonic':100.2,'exit_code':0,
                'ready_sha256':s.hash_bytes((self.ui/'ready.json').read_bytes()),
                'result_sha256':s.hash_bytes((self.ui/'result.json').read_bytes())},
            'waiting_observations':[{'at':101+i*.2,'task_revision':4,'controller_state':'parked',
                'active':False} for i in range(10)],'processes':[{'pid':111,'boundary_revision':5},{'pid':222}]}
        self.summary={'started_monotonic_s':100.,'paint_interval_p95_ms':17.,
                      'stalls_over_50ms_fraction':0}

    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def write(path,value):path.write_bytes(s.encoded(value))

    def flush_events(self):
        (self.controlled/'events.jsonl').write_text(
            ''.join(json.dumps(e)+'\n' for e in self.phase_events),encoding='utf-8')

    def test_earlier_wait_is_retained_but_cannot_supply_foreground_evidence(self):
        self.row['waiting_observations'].insert(0,{'at':95.,'task_revision':4,
            'controller_state':'ready','active':False})
        result=self.run_gate()
        self.assertEqual(result['safe_wait_samples'],10)
        self.assertEqual(result['all_wait_samples_verified'],11)
        self.assertEqual(result['pre_foreground_wait_samples'],1)
        self.assertFalse(result['pre_foreground_samples_counted_toward_gate'])
        self.row['waiting_observations']=self.row['waiting_observations'][:1]+[
            {'at':96+i*.1,'task_revision':4,'controller_state':'ready','active':False}
            for i in range(12)]
        with self.assertRaisesRegex(s.Refused,'foreground_wait_sample_count_or_span'):
            self.run_gate()

    def test_all_samples_must_stay_within_the_same_worker_phase(self):
        for stamp in (89.,201.):
            original=copy.deepcopy(self.row['waiting_observations'])
            self.row['waiting_observations'].append({'at':stamp,'task_revision':4,
                'controller_state':'parked','active':False})
            self.row['waiting_observations'].sort(key=lambda w:w['at'])
            with self.subTest(stamp=stamp),self.assertRaisesRegex(s.Refused,'waiting_outside_agent_attempt'):
                self.run_gate()
            self.row['waiting_observations']=original

    def test_earlier_wait_history_is_validated_even_when_not_counted(self):
        self.row['waiting_observations'].insert(0,{'at':95.,'task_revision':3,
            'controller_state':'ready','active':False})
        invalid=copy.deepcopy(self.history);invalid['operation']={'kind':'generation'}
        with closing(sqlite3.connect(self.hermes/'task.sqlite3')) as db,db:
            db.execute('INSERT INTO history VALUES (?,?,?)',('orders-report',3,json.dumps(invalid)))
        with self.assertRaisesRegex(s.Refused,'waiting_not_durable_safe_boundary'):self.run_gate()

    def test_no_active_request_or_ready_only_period_can_supply_foreground_wait(self):
        for field,value in (('active',True),('controller_state','ready')):
            original=copy.deepcopy(self.row['waiting_observations'])
            self.row['waiting_observations'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(s.Refused,'foreground_wait_not_parked_or_draining'):
                self.run_gate()
            self.row['waiting_observations']=original

    def test_phase_markers_cannot_be_ambiguous_or_unsafe(self):
        original=copy.deepcopy(self.phase_events)
        changes=[original+[original[0]],original[:1],
                 [original[0],{**original[1],'safe_boundary':False}],
                 [{**original[0],'at':101.},original[1]],
                 [original[0],{**original[1],'at':901.}]]
        for events in changes:
            self.phase_events=events;self.flush_events()
            with self.subTest(events=events),self.assertRaises(s.Refused):self.run_gate()

    def test_wait_history_cannot_reference_safe_boundary_or_a_later_revision(self):
        for revision in (5,9):
            with closing(sqlite3.connect(self.hermes/'task.sqlite3')) as db,db:
                db.execute('INSERT INTO history VALUES (?,?,?)',('orders-report',revision,json.dumps(self.history)))
            self.row['waiting_observations'][0]['task_revision']=revision
            with self.subTest(revision=revision),self.assertRaisesRegex(s.Refused,'waiting_revision_outside'):
                self.run_gate()

    def test_wait_history_cannot_go_backwards_inside_a_worker(self):
        with closing(sqlite3.connect(self.hermes/'task.sqlite3')) as db,db:
            db.execute('INSERT INTO history VALUES (?,?,?)',('orders-report',3,json.dumps(self.history)))
        self.row['waiting_observations'][-1]['task_revision']=3
        with self.assertRaisesRegex(s.Refused,'waiting_revision_outside'):self.run_gate()

    def run_gate(self):
        with patch.object(s,'foreground',return_value=(self.summary,{})):
            return s.resource_wait(s.Inputs(self.root),self.controlled,self.hermes,
                                   self.row,self.state,self.before)

    def test_safe_wait_can_pass_without_claiming_live_deferral(self):
        result=self.run_gate()
        self.assertEqual(result['proven_deferrals'],[])
        self.assertEqual(result['safe_wait_samples'],10)
        self.assertEqual(result['waiting_revisions_verified'],1)
        s.privacy_check(s.encoded(result))

    def test_restart_deadline_and_active_readiness_proof_are_required(self):
        self.before['deadline_monotonic']=901.
        with self.assertRaisesRegex(s.Refused,'restart_deadline_changed'):self.run_gate()
        self.before['deadline_monotonic']=900.
        self.row['agent_foreground_process']['same_active_ticket_at_ready']=False
        with self.assertRaisesRegex(s.Refused,'no_active_agent'):self.run_gate()

    def test_waiting_revision_cannot_hide_an_uncertain_generation(self):
        self.history['operation']={'kind':'generation'}
        with closing(sqlite3.connect(self.hermes/'task.sqlite3')) as db, db:
            db.execute('UPDATE history SET payload=?',(json.dumps(self.history),))
        with self.assertRaisesRegex(s.Refused,'waiting_not_durable'):self.run_gate()

    def test_proof_ledger_requires_matching_instance_counts_and_completed_body(self):
        proof={'schema':'adaptive.not-dispatched.v1','http_status':503,'dispatched':False,
               'gateway_instance':'a'*32,'attempt_id':'attempt-1','body_sha256':'b'*64}
        self.state.update(admission_attempts=2,admission_deferrals=[proof])
        self.write(self.hermes/'result-222.json',{'admission_attempts':2,'admission_deferrals':1})
        ledger=[{'proof':proof,'started_at':1.,'finished_at':2.}]
        self.write(self.hermes/'admission-attempts.json',ledger)
        self.assertEqual(len(self.run_gate()['proven_deferrals']),1)
        proof['body_sha256']='c'*64
        self.write(self.hermes/'admission-attempts.json',ledger)
        with self.assertRaisesRegex(s.Refused,'deferred_body_not_completed'):self.run_gate()
        proof['body_sha256']='b'*64;proof['gateway_instance']='c'*32
        self.write(self.hermes/'admission-attempts.json',ledger)
        with self.assertRaisesRegex(s.Refused,'deferral_gateway_changed'):self.run_gate()


class DiagnosticSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve(strict=True)
        self.native=self.root/s.CONTROLLED_NATIVE
        (self.native/'owner_source').mkdir(parents=True)
        self.controlled=self.root/s.CONTROLLED_ATTEMPT;self.controlled.mkdir()
        self.package=self.root/'fixture-package';self.package.mkdir()
        (self.package/'config').mkdir()
        self.owner_run=self.package/'runs'/'owned-attempt';self.owner_run.mkdir(parents=True)
        self.files={};pins={}
        for name in s.OWNER_HELPERS:
            data=('fixture source: '+name).encode()
            (self.native/'owner_source'/name).write_bytes(data)
            (self.package/name).write_bytes(data)
            self.files[name]=s.hash_bytes(data)
            pins[name]={'preserved_sha256':self.files[name]}
        self.write(self.native/'owner_source/source-pins.json',{'files':pins})
        self.template={'idle_unload_s':0,'args':['--resident-budget-gib','32','--max-context','65536'],
                       'log':'@RUN@/server.log','reasoning_effort':'high','reasoning_budget_tokens':8192}
        self.files['config/server-template.json']=self.write(self.package/'config/server-template.json',self.template)
        provenance={'native_sha256':s.NATIVE,'handoff_profile':{'idle_unload_s':0,
                    'idle_controller':'desktop_host','quality_model_guard_changes':False}}
        self.files['PROVENANCE.json']=self.write(self.package/'PROVENANCE.json',provenance)
        self.files['runtime/native/strata.exe']=s.NATIVE
        manifest={'schema':'adaptive-engine-manifest.v1','files':self.files}
        manifest_sha=self.write(self.package/'MANIFEST.json',manifest)
        self.config={'package':str(self.package),'manifest_sha256':manifest_sha,
                     'provenance_sha256':self.files['PROVENANCE.json'],'max_runtime_seconds':900}
        self.write(self.native/'handoff-package.private.json',self.config)
        self.effective=copy.deepcopy(self.template)
        self.effective['log']=self.owner_run.as_posix()+'/server.log'
        self.effective['args'][1]='16'
        effective_sha=self.write(self.owner_run/'server.json',self.effective)
        self.profile={'verification':{k:self.config[k] for k in ('manifest_sha256','provenance_sha256')},
                      'effective_config_sha256':effective_sha}
        self.owner={'run':str(self.owner_run),'startup_cache_plan':{'resident_budget_gib':16}}
        self.write(self.controlled/'initial-owner.private.json',self.owner)
        # Binding unit fixtures substitute their own trusted pin roots. Production
        # constants are separately asserted below; no live receipts are opened.
        package_patch=patch.object(s,'CONTROLLED_PACKAGE_PINS',
            {k:self.config[k] for k in ('manifest_sha256','provenance_sha256')})
        package_patch.start();self.addCleanup(package_patch.stop)
        frozen_patch=patch.dict(s.FROZEN_SOURCE_SHA256,{
            s.CONTROLLED_NATIVE+'/handoff-package.private.json':
                s.hash_bytes((self.native/'handoff-package.private.json').read_bytes()),
            s.CONTROLLED_NATIVE+'/owner_source/source-pins.json':
                s.hash_bytes((self.native/'owner_source/source-pins.json').read_bytes())})
        frozen_patch.start();self.addCleanup(frozen_patch.stop)

    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def write(path,value):
        raw=s.encoded(value);path.write_bytes(raw);return s.hash_bytes(raw)

    def bind(self):
        return s.controlled_native_binding(s.Inputs(self.root),self.profile,self.controlled)

    def test_explicit_successor_selection_cannot_fall_back_to_previous_attempt(self):
        self.assertEqual((s.CONTROLLED_ATTEMPT,s.HERMES_ATTEMPT),('controlled-11','hermes-real-03'))
        self.assertEqual(s.CONTROLLED_HARNESS,'successor-v6/run_validation.py')
        self.assertEqual(s.CONTROLLED_NATIVE,'successor-v6/native')

    def test_package_binding_preserves_hashes_and_exports_no_private_path(self):
        result=self.bind()
        self.assertEqual(result['manifest_sha256'],self.config['manifest_sha256'])
        self.assertEqual(result['owner_helper_sha256'],{k:self.files[k] for k in s.OWNER_HELPERS})
        self.assertTrue(result['template_substitution_and_resident_cache_verified'])
        s.privacy_check(s.encoded(result))

    def test_old_or_changed_package_manifest_is_refused(self):
        self.config['manifest_sha256']='a'*64
        self.write(self.native/'handoff-package.private.json',self.config)
        with self.assertRaisesRegex(s.Refused,'controlled_package_pin_mismatch'):self.bind()

    def test_source_and_installed_helper_must_match_recorded_manifest(self):
        (self.native/'owner_source/engine.py').write_bytes(b'different source')
        with self.assertRaisesRegex(s.Refused,'controlled_helper_source_changed'):self.bind()
        (self.native/'owner_source/engine.py').write_bytes(b'fixture source: engine.py')
        (self.package/'engine.py').write_bytes(b'different installed helper')
        with self.assertRaisesRegex(s.Refused,'controlled_package_helper_changed'):self.bind()

    def test_self_consistent_different_package_still_fails_frozen_selection(self):
        self.config['manifest_sha256']='b'*64
        self.profile['verification']['manifest_sha256']='b'*64
        self.write(self.native/'handoff-package.private.json',self.config)
        with self.assertRaisesRegex(s.Refused,'controlled_frozen_package_changed'):self.bind()

    def test_changed_operator_config_or_source_pin_file_is_refused(self):
        self.config['max_runtime_seconds']=901
        self.write(self.native/'handoff-package.private.json',self.config)
        with self.assertRaisesRegex(s.Refused,'controlled_frozen_config_changed'):self.bind()
        self.config['max_runtime_seconds']=900
        self.write(self.native/'handoff-package.private.json',self.config)
        pins=json.loads((self.native/'owner_source/source-pins.json').read_bytes())
        pins['extra']='a changed pin document is a different source selection'
        self.write(self.native/'owner_source/source-pins.json',pins)
        with self.assertRaisesRegex(s.Refused,'controlled_frozen_owner_pins_changed'):self.bind()

    def test_effective_config_requires_recorded_hash_and_only_existing_template_changes(self):
        self.effective['reasoning_budget_tokens']=1
        updated=self.write(self.owner_run/'server.json',self.effective)
        with self.assertRaisesRegex(s.Refused,'controlled_effective_config_changed'):self.bind()
        self.profile['effective_config_sha256']=updated
        with self.assertRaisesRegex(s.Refused,'controlled_effective_template_mismatch'):self.bind()

    def test_missing_owner_run_or_outside_package_cannot_supply_config(self):
        other=self.root/'unrelated';other.mkdir()
        self.owner['run']=str(other)
        self.write(self.controlled/'initial-owner.private.json',self.owner)
        with self.assertRaisesRegex(s.Refused,'controlled_owner_run_outside_package'):self.bind()

    def test_interrupted_attempt_remains_external_observation_without_terminal_acceptance(self):
        directory=self.root/'controlled-04';directory.mkdir()
        row={'schema':'adaptive.external-interruption.v1','passed':False,'qualification_accepted':False,
             'last_host_phase':'waiting_foreground','last_scheduler':{'active':False,'pending':0,'completed':0},
             'verification':{'owned_test_python_processes':0,'listeners_18098_18100':0},
             'actual_foreground_process':'PRIVATE_APPLICATION','actual_foreground_pid':123}
        self.write(directory/'interruption.private.json',row)
        result=s.interrupted_attempt(s.Inputs(self.root))
        self.assertFalse(result['terminal_result_present'])
        self.assertFalse(result['normal_native_release_claimed'])
        self.assertNotIn('PRIVATE',json.dumps(result));s.privacy_check(s.encoded(result))
        row['qualification_accepted']=True
        self.write(directory/'interruption.private.json',row)
        with self.assertRaisesRegex(s.Refused,'interruption_reclassified_as_accepted'):
            s.interrupted_attempt(s.Inputs(self.root))
        self.write(directory/'result.private.json',{'passed':True})
        with self.assertRaisesRegex(s.Refused,'interrupted_attempt_gained_terminal_result'):
            s.interrupted_attempt(s.Inputs(self.root))


class FrozenSelectionTests(unittest.TestCase):
    def test_production_selection_is_controlled11_v6_and_exact_package(self):
        self.assertEqual(s.CONTROLLED_ATTEMPT,'controlled-11')
        self.assertEqual(s.CONTROLLED_HARNESS,'successor-v6/run_validation.py')
        self.assertEqual(s.CONTROLLED_NATIVE,'successor-v6/native')
        self.assertEqual(s.CONTROLLED_PACKAGE_PINS,{
            'manifest_sha256':'ce79f32813a632df14e043c020789b1de9260aa34518e5f62f05645323e78213',
            'provenance_sha256':'0b101e1150043deaae22722895712902f0c9aa0fb7e1ce7eef91b5386ad2e9b4'})
        runtime={name for name in s.FROZEN_SOURCE_SHA256 if name.startswith('src/')}
        self.assertEqual(runtime,{'src/adaptive_inference/'+name for name in
            ('gateway.py','scheduler.py','handoff.py','task_store.py','config.py','costs.py','feedback.py')})
        self.assertEqual(len(s.FROZEN_SOURCE_SHA256),21)
        for sha in s.FROZEN_SOURCE_SHA256.values():self.assertEqual(s.digest(sha),sha)
        self.assertEqual(s.FROZEN_SOURCE_SHA256[s.CONTROLLED_HARNESS],
            '0521d7c16570728e7259610f80eedec778e8039ff309323154cc308fae8bd280')
        self.assertEqual(s.FROZEN_SOURCE_SHA256['src/adaptive_inference/handoff.py'],
            '5b11f25a62d27c2b7f78776a9c05a2c15c0712def9fbad52dddd319232d0ed23')
        self.assertEqual(s.HISTORICAL_SHUTDOWN_HARNESS_SHA256,
            '2f5315dcf53831509493e7f451e187a4ab748072f42992e9997aa17b17f8118e')

    def test_prior_positive_attempt_cannot_replace_missing_or_failed_selected_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);comparison=root/'comparison.json';comparison.write_text('{}')
            uncontrolled=root/'uncontrolled-04';uncontrolled.mkdir()
            row={'passed':True,'model':s.MODEL,'quality':s.QUALITY,'case':'uncontrolled',
                 'gateway_default_class':'normal','standalone_generation_class':'background'}
            (uncontrolled/'result.private.json').write_bytes(s.encoded(row))
            for prior in ('controlled-05','controlled-06','controlled-07','controlled-08','controlled-09','controlled-10'):
                directory=root/prior;directory.mkdir()
                (directory/'result.private.json').write_bytes(s.encoded({**row,'case':'controlled'}))
            selected=root/s.CONTROLLED_ATTEMPT;selected.mkdir()
            output=root/'must-not-exist'
            for terminal in (None,{'passed':False}):
                with self.subTest(terminal=terminal):
                    if terminal is not None:
                        (selected/'result.private.json').write_bytes(s.encoded(terminal))
                    error=io.StringIO()
                    with redirect_stderr(error):
                        code=s.main(['--root',str(root),'--comparison',str(comparison),'--output',str(output)])
                    self.assertEqual(code,2);self.assertFalse(output.exists())
                    if terminal is not None:self.assertIn('controlled_failed',error.getvalue())

    def test_additional_failed_attempts_cannot_be_reclassified_or_hide_generation(self):
        class Inputs:
            def __init__(self,root):
                self.root=root
                self.rows={name:{'passed':False,'handoff_events':[]} for name in
                    ('uncontrolled-01','uncontrolled-02','uncontrolled-03','controlled-01',
                     'controlled-02','controlled-03','controlled-05','controlled-06',
                     'controlled-07','controlled-08','controlled-09')}
                self.rows['controlled-07']['error']='TimeoutError: Desktop admission did not become ready'
                self.rows['controlled-08']['error']='OwnerStartupError: New owner failed before readiness; see its retained run receipt'
                self.rows['controlled-09']['error']='RuntimeError: Arithmetic artifact failed independent acceptance'
            def read(self,label,path):
                if path.name=='ui-watch-completed.json':
                    return {'ordinary_input_actions':0,'terminal_passed':False}
                return self.rows[path.parent.name]
        with tempfile.TemporaryDirectory() as folder:
            inputs=Inputs(Path(folder))
            with patch.object(s,'interrupted_attempt',return_value={'attempt':'controlled-04','interrupted':True}), patch.object(s,'unaccepted_shutdown_attempt',return_value={'attempt':'controlled-10','qualification_accepted':False}):
                rows=s.failed_attempts(inputs)
                for label in ('controlled-07','controlled-08','controlled-09'):
                    self.assertFalse(next(row for row in rows if row['attempt']==label)['included_in_comparison'])
                    inputs.rows[label]['passed']=True
                    with self.assertRaisesRegex(s.Refused,'excluded_failure_reclassified'):s.failed_attempts(inputs)
                    inputs.rows[label]['passed']=False
                    inputs.rows[label]['inference']=[{'completed':True}]
                    with self.assertRaisesRegex(s.Refused,'excluded_.*scope_changed'):s.failed_attempts(inputs)
                    del inputs.rows[label]['inference']


class ArithmeticFeedbackExportTests(unittest.TestCase):
    FEEDBACK=('The independent arithmetic check rejected the result. Recount CSV data rows, '
              'sum quantities, multiply quantity by unit_cents for each row, group all repeated '
              'item rows, and sum the item totals. Recompute from the original CSV.')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.directory=self.root/s.CONTROLLED_ATTEMPT;self.directory.mkdir()
        self.attempts=[];self.rows=[];tasks=[];position=0
        for index,count in enumerate((2,1)):
            messages=[{'role':'user','content':s.ARITHMETIC_PROMPT}];local=[]
            for attempt in range(1,count+1):
                accepted=attempt==count
                answer=copy.deepcopy(s.ARITHMETIC)
                if not accepted:answer['units']+=1
                content=json.dumps(answer);feedback='' if accepted else self.FEEDBACK
                stem=f'task-{index}-attempt-{attempt}'
                body={'model':s.MODEL,'messages':copy.deepcopy(messages),**s.QUALITY}
                data={'model':s.MODEL,'choices':[{'message':{'role':'assistant','content':content,
                    'reasoning_content':'PRIVATE_REASONING_SENTINEL'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110},
                    'private_path':r'C:\Private\never-export'}
                raw=json.dumps(data).encode()
                row={'index':index,'attempt':attempt,'request_index':position,'requested_at':position*10+1,
                     'completed_at':position*10+5,'status':'validated','verdict':{'accepted':accepted,'feedback':feedback},
                     'model':s.MODEL,'quality':s.QUALITY,'request_class':'background','gateway_class':'background',
                     'request_file':stem+'-request.private.json','response_file':stem+'-response.private.bin',
                     'request_sha256':s.hash_bytes(json.dumps(body,sort_keys=True).encode()),
                     'response_sha256':s.hash_bytes(raw),'http_status':200,'finish_reason':'stop',
                     'usage':data['usage'],'retryable':not accepted and attempt<3}
                if accepted:row['answer']=answer
                self.write(row['request_file'],body);(self.directory/row['response_file']).write_bytes(raw)
                self.write(stem+'-response.private.json',data)
                self.attempts.append(row);local.append(row);position+=1
                if not accepted:messages.extend([{'role':'assistant','content':content},
                    {'role':'user','content':s.CORRECTION_PREFIX+feedback}])
            final=local[-1]
            receipt={key:final[key] for key in ('answer','finish_reason','usage','quality','model',
                'request_class','gateway_class','request_sha256')}
            receipt.update(index=index,requested_at=local[0]['requested_at'],completed_at=final['completed_at'],
                           attempts=count,request_count=count,max_attempts=3,
                           attempt_request_indices=[r['request_index'] for r in local])
            self.rows.append(receipt);tasks.append({'index':index,'status':'accepted','accepted':True,'attempts':count})
        self.ledger={'logical_task_count':2,'maximum_attempts_per_task':3,'maximum_requests':6,
                     'request_count':len(self.attempts),'tasks':tasks}
        self.flush()

    def write(self,name,value):(self.directory/name).write_bytes(s.encoded(value))
    def read(self,name):return s.parse((self.directory/name).read_bytes())
    def flush(self):
        self.write('inference-attempts.private.json',self.attempts)
        self.write('inference-tasks.private.json',self.ledger)
        self.write('inference-receipts.json',self.rows)
    def validate(self):return s.arithmetic_feedback(s.Inputs(self.root),self.directory,self.rows)
    def replace_response(self,position,data):
        row=self.attempts[position];raw=json.dumps(data).encode()
        (self.directory/row['response_file']).write_bytes(raw)
        self.write(f"task-{row['index']}-attempt-{row['attempt']}-response.private.json",data)
        row['response_sha256']=s.hash_bytes(raw);self.flush()

    def test_full_chain_succeeds_with_explicit_task_and_request_timing_and_privacy(self):
        result=self.validate()
        self.assertEqual((result['logical_task_count'],result['request_count']),(2,3))
        self.assertEqual(result['first_request_completed_at'],5)
        self.assertEqual(result['logical_tasks'][0]['completed_at'],15)
        self.assertEqual(result['logical_tasks'][0]['logical_task_duration_s'],14)
        self.assertIn('final_request_usage',result['logical_tasks'][0])
        self.assertNotIn('usage',result['logical_tasks'][0])
        self.assertEqual([a['accepted'] for a in result['attempts']],[False,True,True])
        encoded=s.encoded(result);s.privacy_check(encoded)
        for private in (b'PRIVATE_REASONING',b'never-export',b'Calculate this CSV',b'Recompute from',b'"feedback":'):
            self.assertNotIn(private,encoded)

    def test_missing_and_reordered_attempts_refused(self):
        original=copy.deepcopy(self.attempts)
        for changed in ([original[1],original[0],original[2]],original[1:]):
            with self.subTest(changed=changed):
                self.attempts=changed;self.flush()
                with self.assertRaises(s.Refused):self.validate()

    def test_altered_quality_or_original_prompt_or_actual_feedback_chain_refused(self):
        name='task-0-attempt-2-request.private.json';original=self.read(name)
        for kind in ('quality','original','rejected','feedback'):
            body=copy.deepcopy(original)
            if kind=='quality':body['max_tokens']=100
            elif kind=='original':body['messages'][0]['content']='Different task'
            elif kind=='rejected':body['messages'][1]['content']='Replaced rejected answer'
            else:body['messages'][2]['content']='The answer is '+json.dumps(s.ARITHMETIC)
            self.write(name,body)
            # Even updating the matching digest cannot replace trusted content.
            self.attempts[1]['request_sha256']=s.hash_bytes(json.dumps(body,sort_keys=True).encode());self.flush()
            with self.subTest(kind=kind),self.assertRaisesRegex(s.Refused,'feedback_chain_changed'):self.validate()

    def test_tampered_verdict_or_hidden_fatal_never_passes(self):
        original=copy.deepcopy(self.attempts)
        for update in ({'verdict':{'accepted':True,'feedback':''}},
                       {'verdict':{'accepted':False,'feedback':'invented validator feedback'}},
                       {'status':'fatal_error'},{'error':'private transport failure'},
                       {'retryable':False},{'http_status':503},{'gateway_class':'normal'}):
            self.attempts=copy.deepcopy(original);self.attempts[0].update(update);self.flush()
            with self.subTest(update=update),self.assertRaises(s.Refused):self.validate()

    def test_prior_rejection_must_really_fail_independent_acceptance(self):
        data=self.read('task-0-attempt-1-response.private.json')
        data['choices'][0]['message']['content']=json.dumps(s.ARITHMETIC)
        self.replace_response(0,data)
        with self.assertRaisesRegex(s.Refused,'arithmetic_verdict_changed'):self.validate()

    def test_incorrect_accepted_content_refused_even_when_hashes_match(self):
        data=self.read('task-0-attempt-2-response.private.json')
        wrong=copy.deepcopy(s.ARITHMETIC);wrong['total_cents']+=1
        data['choices'][0]['message']['content']=json.dumps(wrong);self.replace_response(1,data)
        with self.assertRaisesRegex(s.Refused,'arithmetic_verdict_changed'):self.validate()

    def test_float_boolean_duplicate_or_fenced_final_answer_is_not_accepted(self):
        good=json.dumps(s.ARITHMETIC)
        bad=[good.replace('"rows": 4','"rows": 4.0'),good.replace('"rows": 4','"rows": true'),
             good.replace('"rows": 4','"rows": 9, "rows": 4'),'```json\n'+good+'\n```']
        for content in bad:
            with self.subTest(content=content):
                verdict=s.arithmetic_verdict(content,'stop');self.assertFalse(verdict['accepted'])
                self.assertNotIn('4350',verdict['feedback'])

    def test_exhausted_or_unaccepted_task_and_hidden_attempt_refused(self):
        original=copy.deepcopy(self.ledger)
        for update in ({'status':'exhausted','accepted':False},{'attempts':4},{'status':'fatal_error'}):
            self.ledger=copy.deepcopy(original);self.ledger['tasks'][0].update(update);self.flush()
            with self.subTest(update=update),self.assertRaises(s.Refused):self.validate()
        self.ledger=original;self.attempts.append(copy.deepcopy(self.attempts[-1]));self.ledger['request_count']=4;self.flush()
        with self.assertRaisesRegex(s.Refused,'hidden_attempts'):self.validate()

    def test_missing_response_or_unlisted_attempt_file_refused(self):
        path=self.directory/'task-0-attempt-1-response.private.bin'
        data=path.read_bytes();path.unlink()
        with self.assertRaises(OSError):self.validate()
        path.write_bytes(data)
        self.write('task-0-attempt-4-request.private.json',{})
        with self.assertRaisesRegex(s.Refused,'unlisted_attempt_files'):self.validate()

    def test_fixed_paths_and_raw_response_hash_required(self):
        original=copy.deepcopy(self.attempts)
        for update in ({'request_file':'../../elsewhere.json'},{'response_file':'elsewhere.bin'},
                       {'response_sha256':'0'*64},{'request_sha256':'0'*64}):
            self.attempts=copy.deepcopy(original);self.attempts[0].update(update);self.flush()
            with self.subTest(update=update),self.assertRaises(s.Refused):self.validate()

    def test_attempt_times_are_sequential_and_task_receipt_cannot_hide_duration(self):
        original=copy.deepcopy(self.attempts)
        for update in ({'requested_at':2},{'completed_at':0}):
            self.attempts=copy.deepcopy(original);self.attempts[1].update(update);self.flush()
            with self.subTest(update=update),self.assertRaisesRegex(s.Refused,'times_reordered'):self.validate()
        self.attempts=original;self.flush();self.rows[0]['requested_at']=11
        with self.assertRaisesRegex(s.Refused,'task_start_changed'):self.validate()

    def test_boolean_task_index_cannot_alias_integer_zero(self):
        self.rows[0]['index']=False
        with self.assertRaisesRegex(s.Refused,'task_index_changed'):self.validate()

    def test_release_compares_first_http_completion_not_corrected_logical_task_completion(self):
        result=self.validate();events=[{'at':3,'to':'draining'},{'at':8,'release':{}}]
        timing=s.release_timing(events,2,result['first_request_completed_at'])
        self.assertEqual(timing['release_after_first_completion_s'],3)
        self.assertLess(8,result['logical_tasks'][0]['completed_at'])
        with self.assertRaisesRegex(s.Refused,'release_before_active_response_completed'):
            s.release_timing([{'at':3,'to':'draining'},{'at':4,'release':{}}],2,result['first_request_completed_at'])

    def test_other_v4_acceptance_functions_remain_unchanged(self):
        root=Path(__file__).resolve().parent
        def functions(name):
            tree=ast.parse((root/name).read_text(encoding='utf-8'))
            return {n.name:ast.dump(n,include_attributes=False) for n in tree.body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        old=functions('sanitize_milestone_v6.py');new=functions('sanitize_milestone_v7.py')
        for name in old:
            if name not in ('build','failed_attempts'):
                self.assertEqual(old[name],new[name],name)


class TerminalControllerTests(unittest.TestCase):
    @staticmethod
    def status():
        return {'running':False,'host_phase':'closed',
                'controller':{'fault':None,'handoff_state':'parked','admission_allowed':False},
                'scheduler':{'closing':True,'active':False,'pending':0,'backend_completion_uncertain':False},
                'private_path':r'C:\Private\do-not-copy','activity':{'pid':123}}

    def test_clean_terminal_is_allowlisted_without_private_status(self):
        result=s.terminal_status(self.status())
        self.assertEqual(result['controller']['fault'],None)
        self.assertEqual(result['controller']['handoff_state'],'parked')
        self.assertNotIn('private',json.dumps(result));s.privacy_check(s.encoded(result))

    def test_controller_fault_state_missing_fault_or_unknown_state_refused(self):
        for change in ({'fault':'gateway_completion_unreconciled'},{'handoff_state':'fault'},
                       {'handoff_state':'unknown'},{'handoff_state':None},{'admission_allowed':True}):
            with self.subTest(change=change):
                status=self.status();status['controller'].update(change)
                with self.assertRaisesRegex(s.Refused,'terminal_controller_not_reconciled'):
                    s.terminal_status(status)
        status=self.status();del status['controller']['fault']
        with self.assertRaisesRegex(s.Refused,'terminal_controller_not_reconciled'):s.terminal_status(status)

    def test_clean_controller_does_not_override_scheduler_uncertainty_or_ownership(self):
        for change in ({'closing':False},{'active':True},{'pending':1},{'backend_completion_uncertain':True}):
            with self.subTest(change=change):
                status=self.status();status['scheduler'].update(change)
                with self.assertRaisesRegex(s.Refused,'terminal_gateway_not_reconciled'):
                    s.terminal_status(status)

    def test_build_uses_terminal_gate_and_keeps_fault_event_refusal(self):
        tree=ast.parse(Path(s.__file__).read_text(encoding='utf-8'))
        build=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                            and n.func.id=='terminal_status' for n in ast.walk(build)))
        with self.assertRaisesRegex(s.Refused,'invalid_handoff_transition'):
            s.handoff_events([{'at':1,'from':'parked','to':'fault'}])


class CompleteLedgerTests(unittest.TestCase):
    def setUp(self):
        self.raw=[{'at':1,'from':'ready','to':'draining'},
                  {'at':2,'from':'draining','to':'releasing'},
                  {'at':3,'release':{'owner_id':'a'*32,'released':True,'cleanup_confirmed':True,
                       'port_free':True,'retained_processes':10,'confirmed_process_exits':10,
                       'server_exit_code':0}},
                  {'at':3,'from':'releasing','to':'parked'}]
        self.public=copy.deepcopy(self.raw)
        del self.public[2]['release']['server_exit_code']

    def test_only_optional_zero_exit_code_is_normalized_and_retained(self):
        result=s.matching_handoff_ledgers(self.raw,self.public)
        self.assertEqual(result[2]['release']['server_exit_code'],0)
        self.assertEqual(len(result),len(self.raw))
        self.assertNotIn('server_exit_code',self.public[2]['release'])
        s.privacy_check(s.encoded(result))

    def test_nonzero_exit_in_either_ledger_cannot_be_normalized_away(self):
        for target in ('raw','public'):
            with self.subTest(target=target):
                raw,public=copy.deepcopy(self.raw),copy.deepcopy(self.public)
                (raw if target=='raw' else public)[2]['release']['server_exit_code']=1
                with self.assertRaisesRegex(s.Refused,'native_server_exit'):
                    s.matching_handoff_ledgers(raw,public)

    def test_no_missing_added_reordered_or_changed_event_is_accepted(self):
        changed=[]
        changed.append(self.public[:-1])
        changed.append(self.public+[{'at':4,'from':'parked','to':'restoring'}])
        swapped=copy.deepcopy(self.public);swapped[2],swapped[3]=swapped[3],swapped[2];changed.append(swapped)
        timestamp=copy.deepcopy(self.public);timestamp[2]['at']=2.5;changed.append(timestamp)
        transition=copy.deepcopy(self.public);transition[3]['from']='ready';changed.append(transition)
        for public in changed:
            with self.subTest(public=public),self.assertRaises(s.Refused):
                s.matching_handoff_ledgers(self.raw,public)

    def test_owner_count_release_flags_and_exit_proofs_remain_exact(self):
        for change in ({'owner_id':'b'*32},{'retained_processes':9,'confirmed_process_exits':9},
                       {'released':False},{'cleanup_confirmed':False},{'port_free':False},
                       {'confirmed_process_exits':9}):
            with self.subTest(change=change):
                public=copy.deepcopy(self.public);public[2]['release'].update(change)
                with self.assertRaises(s.Refused):s.matching_handoff_ledgers(self.raw,public)

    def test_terminal_fault_in_either_full_ledger_is_still_refused(self):
        fault={'at':4,'from':'parked','to':'fault'}
        for raw,public in ((self.raw+[fault],self.public),(self.raw,self.public+[fault])):
            with self.subTest(raw_length=len(raw)),self.assertRaisesRegex(s.Refused,'invalid_handoff_transition'):
                s.matching_handoff_ledgers(raw,public)


class HistoricalShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.directory=self.root/'controlled-10'
        (self.directory/'host').mkdir(parents=True)
        source=self.root/'successor-v5/run_validation.py';source.parent.mkdir()
        source.write_bytes(b'bounded historical harness fixture')
        self.source=source;self.expected=s.hash_bytes(source.read_bytes())
        patcher=patch.object(s,'HISTORICAL_SHUTDOWN_HARNESS_SHA256',self.expected)
        patcher.start();self.addCleanup(patcher.stop)
        self.prefix=[{'at':1,'from':'uninitialized','to':'ready'},
                     {'at':2,'from':'ready','to':'draining'},
                     {'at':3,'from':'draining','to':'releasing'}]
        self.proof={'owner_id':'a'*32,'released':True,'cleanup_confirmed':True,
                    'port_free':True,'retained_processes':10,'confirmed_process_exits':10}
        self.events=self.prefix+[{'at':4,'release':self.proof},
            {'at':4,'from':'releasing','to':'parked'},{'at':4,'from':'parked','to':'fault'}]
        self.cleanup={'closed':True,'owned_children_exited':True,'events':self.events}
        self.row={'passed':True,'case':'controlled','model':s.MODEL,'quality':s.QUALITY,
            'harness_sha256':self.expected,'runtime_source_unchanged':True,
            'runtime_source_sha256':{'src/adaptive_inference/handoff.py':
                'a6fa8da1a408eacf151971aa4b488fcc1ca515cb84b9a63451dc14ecdfd44a72'},
            'handoff_events':copy.deepcopy(self.prefix),'cleanup':self.cleanup,
            'private_path':r'C:\Private\secret','messages':['PRIVATE_MESSAGE']}
        self.status={'running':False,'host_phase':'closed','events':self.events,
            'controller':{'fault':'gateway_completion_unreconciled','handoff_state':'fault','admission_allowed':False},
            'scheduler':{'closing':True,'active':False,'pending':0,'backend_completion_uncertain':False},
            'private_path':r'C:\Private\secret','activity':{'pid':123}}
        self.flush()

    def flush(self):
        for path,row in [('result.private.json',self.row),('host/result.json',self.cleanup),
                         ('host/status.json',self.status)]:
            (self.directory/path).write_bytes(s.encoded(row))

    def validate(self):
        self.flush();inputs=s.Inputs(self.root)
        row=s.unaccepted_shutdown_attempt(inputs)
        inputs.unchanged();return row

    def test_original_pass_preserved_but_qualification_explicitly_false(self):
        result=self.validate()
        self.assertIs(result['recorded_passed'],True)
        self.assertIs(result['qualification_accepted'],False)
        self.assertIs(result['included_in_comparison'],False)
        self.assertEqual(result['terminal_controller_fault'],'gateway_completion_unreconciled')
        self.assertEqual(result['verified_final_release_processes'],10)
        self.assertNotIn('PRIVATE',json.dumps(result));s.privacy_check(s.encoded(result))

    def test_recorded_pass_cannot_be_relabelled_or_harness_rebound(self):
        for key,value in [('passed',False),('passed',1),('harness_sha256','b'*64),
                          ('runtime_source_unchanged',False),('error','PRIVATE_ERROR')]:
            with self.subTest(key=key):
                before=copy.deepcopy(self.row);self.row[key]=value
                with self.assertRaises(s.Refused):self.validate()
                self.row=before
        self.source.write_bytes(b'a different historical harness')
        with self.assertRaisesRegex(s.Refused,'excluded_shutdown_harness_source_changed'):self.validate()

    def test_old_runtime_pin_and_closed_scheduler_are_required(self):
        self.row['runtime_source_sha256']['src/adaptive_inference/handoff.py']='a'*64
        with self.assertRaisesRegex(s.Refused,'excluded_shutdown_runtime_changed'):self.validate()
        self.row['runtime_source_sha256']['src/adaptive_inference/handoff.py']='a6fa8da1a408eacf151971aa4b488fcc1ca515cb84b9a63451dc14ecdfd44a72'
        original=copy.deepcopy(self.status['scheduler'])
        for change in ({'closing':False},{'active':True},{'pending':1},{'pending':False},
                       {'backend_completion_uncertain':True}):
            with self.subTest(change=change):
                self.status['scheduler']={**original,**change}
                with self.assertRaises(s.Refused):self.validate()
        self.status['scheduler']=original

    def test_actual_fault_and_transition_required_without_exporting_arbitrary_error(self):
        original=copy.deepcopy(self.status['controller'])
        for change in ({'fault':None},{'fault':r'C:\Private\arbitrary-error'},
                       {'handoff_state':'parked'},{'admission_allowed':True}):
            with self.subTest(change=change):
                self.status['controller']={**original,**change}
                with self.assertRaises(s.Refused):self.validate()
        self.status['controller']=original
        self.events[-1]['to']='parked'
        with self.assertRaisesRegex(s.Refused,'excluded_shutdown_fault_transition_changed'):self.validate()

    def test_release_proof_and_preclose_ledger_cannot_be_discarded(self):
        self.proof['confirmed_process_exits']=9
        with self.assertRaisesRegex(s.Refused,'release_exit_count'):self.validate()
        self.proof['confirmed_process_exits']=10
        self.row['handoff_events']=[]
        with self.assertRaises(s.Refused):self.validate()

    def test_full_terminal_ledgers_must_agree(self):
        self.status['events']=copy.deepcopy(self.events)
        self.status['events'][-1]['at']=5
        with self.assertRaisesRegex(s.Refused,'excluded_shutdown_terminal_ledger_mismatch'):self.validate()


if __name__=='__main__':unittest.main()
