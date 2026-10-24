"""Independent adversarial timing probes; only local fake HTTP backends."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent/'runtime-timing-prototype'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import asyncio
import time
import unittest
from aiohttp import web
from test_runtime_timing import RuntimeTests,owner,warm,RequestCostModel,RuntimeTimingContext

class Additional(RuntimeTests):
    async def test_unbound_queue_can_bind_before_its_first_dispatch(self):
        request=asyncio.create_task(self.request())
        try:
            for _ in range(100):
                if self.gateway.scheduler.pending:break
                await asyncio.sleep(.005)
            self.assertEqual(len(self.gateway.scheduler.pending),1)
            ticket=next(iter(self.gateway.scheduler.pending.values()))
            identity=(ticket.sequence,ticket.arrival,ticket.rank)
            self.gateway.activate_runtime(owner('first-after-queue'))
            self.assertIs(next(iter(self.gateway.scheduler.pending.values())),ticket)
            self.assertEqual((ticket.sequence,ticket.arrival,ticket.rank),identity)
            self.allowed=True
            self.assertEqual((await request).status,200)
            row=self.gateway.history[-1]
            self.assertIsNone(row['prediction_runtime_generation'])
            self.assertEqual(row['prediction']['reason'],'runtime_unbound')
            self.assertEqual(row['execution_runtime_generation'],1)
            self.assertFalse(row['prediction_matches_execution_runtime'])
            self.assertIsNone(self.gateway._runtime_error)
            self.assertEqual(self.gateway.costs.predict(self.key,now=time.monotonic())['samples'],1)
        finally:
            if not request.done():request.cancel();await asyncio.gather(request,return_exceptions=True)

    async def test_reappearing_owner_label_cannot_resurrect_historical_samples(self):
        self.activate('A');warm(self.gateway.costs,self.key,11)
        original=self.gateway._runtime_context
        self.activate('B');warm(self.gateway.costs,self.key,5)
        second=self.gateway._runtime_context
        self.activate('A')
        self.assertEqual(self.gateway._runtime_context.generation,3)
        self.assertIsNot(self.gateway.costs,original.learner)
        self.assertIsNot(self.gateway.costs,second.learner)
        self.assertEqual(self.gateway._prediction(self.key)[0]['samples'],0)
        self.assertEqual((await self.request()).status,200)
        self.assertEqual(original.learner.predict(self.key,now=time.monotonic())['samples'],3)
        self.assertEqual(second.learner.predict(self.key,now=time.monotonic())['samples'],3)
        self.assertEqual(self.gateway._prediction(self.key)[0]['samples'],1)

    async def test_cancelled_queued_request_does_not_train_replacement(self):
        self.activate('A');warm(self.gateway.costs,self.key,2)
        self.allowed=False
        request=asyncio.create_task(self.request())
        try:
            for _ in range(100):
                if self.gateway.scheduler.pending:break
                await asyncio.sleep(.005)
            self.assertEqual(len(self.gateway.scheduler.pending),1)
            self.gateway.activate_runtime(owner('B'))
            baseline=self.gateway.costs.status()
            request.cancel();await asyncio.gather(request,return_exceptions=True)
            for _ in range(100):
                if not self.gateway.scheduler.pending:break
                await asyncio.sleep(.005)
            self.assertFalse(self.gateway.scheduler.pending)
            self.assertIsNone(self.gateway.scheduler.active)
            self.assertEqual(self.gateway.costs.status(),baseline)
            self.assertFalse(self.seen);self.assertFalse(self.gateway.history)
        finally:
            if not request.done():request.cancel();await asyncio.gather(request,return_exceptions=True)

    async def test_successful_stream_trains_captured_old_learner_only(self):
        self.activate('A');old=self.gateway._runtime_context
        warm(old.learner,self.key,2)
        replacement=RequestCostModel();warm(replacement,self.key,7)
        baseline=replacement.status()
        async def reply(request):
            # Adversarial injection, not an allowed host transition during dispatch.
            self.gateway._runtime_context=RuntimeTimingContext(2,b'fixture',replacement)
            self.gateway.costs=replacement
            return web.Response(text='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',content_type='text/event-stream')
        self.reply_hook=reply
        self.assertEqual((await self.request()).status,200)
        self.assertEqual(replacement.status(),baseline)
        self.assertEqual(old.learner.predict(self.key,now=time.monotonic())['samples'],4)
        self.assertTrue(self.gateway.history[-1]['trained'])
        self.assertEqual(self.gateway.history[-1]['execution_runtime_generation'],1)

if __name__=='__main__':
    names=[n for n in Additional.__dict__ if n.startswith('test_')]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(Additional(n) for n in names))
    raise SystemExit(not result.wasSuccessful())
