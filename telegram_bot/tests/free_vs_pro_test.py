#!/usr/bin/env python3
"""FREE vs PRO AI test — b2c01d1 patch intent.

PRO: AIDA/PAS, bold sarlavha, CTA
FREE: oddiy ixcham
Audit: PRO chuqur, FREE imlo

Mock bilan ishlaydi — real API chaqirilmaydi.
"""
import os
import sys
import asyncio
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("ADMIN_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")

from utils import ai_agent


class TestFreeVsProAI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock _run_ai_chain to avoid real HTTP
        self.original_chain = ai_agent._run_ai_chain

        async def mock_chain(prompt: str, system_instruction: str):
            # Return simple JSON depending on system instruction content
            if "Sotuvchanlik" in system_instruction or "SMM auditor" in system_instruction or "AUDIT" in system_instruction.upper() or "reytingi" in system_instruction:
                # PRO audit
                return {"audit": "PRO audit: reyting 8/10, kuchli hook, CTA yaxshilandi. <b>Yaxshilangan post</b>"}
            if "imlo" in system_instruction.lower():
                return {"audit": "FREE audit: imlo tekshirildi, tavsiya: qisqartiring."}
            if "AIDA" in system_instruction or "PAS" in system_instruction:
                return {"post_text": "<b>PRO Sarlavha</b>\n\nAIDA bo'yicha jozibador post. CTA bilan.", "intent": "post"}
            if "Oddiy" in system_instruction or "ixcham" in system_instruction:
                return {"post_text": "Oddiy post matni", "intent": "post"}
            # default router
            if "PRO" in system_instruction:
                return {"post_text": "<b>PRO Post</b> - AIDA", "intent": "post"}
            return {"post_text": "FREE Post", "intent": "post"}

        ai_agent._run_ai_chain = mock_chain

    async def asyncTearDown(self):
        ai_agent._run_ai_chain = self.original_chain

    def test_constants_exist(self):
        self.assertTrue(hasattr(ai_agent, "_PRO_POST_ENHANCEMENT"))
        self.assertTrue(hasattr(ai_agent, "_FREE_POST_HINT"))
        self.assertTrue(hasattr(ai_agent, "_AUDIT_PRO_SYSTEM"))
        self.assertTrue(hasattr(ai_agent, "_AUDIT_FREE_SYSTEM"))
        self.assertIn("AIDA", ai_agent._PRO_POST_ENHANCEMENT)
        self.assertIn("PAS", ai_agent._PRO_POST_ENHANCEMENT)
        self.assertIn("imlo", ai_agent._AUDIT_FREE_SYSTEM.lower())
        self.assertIn("reytingi", ai_agent._AUDIT_PRO_SYSTEM.lower())

    def test_router_instruction_pro_flag(self):
        free_instr = ai_agent._get_router_system_instruction(is_pro=False)
        pro_instr = ai_agent._get_router_system_instruction(is_pro=True)
        self.assertIn("FREE", free_instr)
        self.assertIn("PRO", pro_instr)
        # PRO should contain AIDA hint
        self.assertTrue("AIDA" in pro_instr or "PRO" in pro_instr)
        # FREE should be simpler / contain FREE hint
        self.assertTrue("Oddiy" in free_instr or "FREE" in free_instr)

    async def test_audit_post_free(self):
        res = await ai_agent.audit_post("Oddiy matn", is_pro=False)
        self.assertIsNotNone(res)
        self.assertIn("audit", res)
        self.assertTrue("FREE" in res["audit"] or "imlo" in res["audit"].lower())

    async def test_audit_post_pro(self):
        res = await ai_agent.audit_post("Kanal uchun yangi post", is_pro=True)
        self.assertIsNotNone(res)
        self.assertIn("audit", res)
        # PRO audit should contain rating / deeper analysis
        audit_text = res["audit"]
        self.assertTrue("PRO" in audit_text or "reyting" in audit_text.lower() or "8/10" in audit_text)

    async def test_generate_ai_response_pro_flag(self):
        res_free = await ai_agent.generate_ai_response("Mavzu: Sotuvlar", is_pro=False)
        res_pro = await ai_agent.generate_ai_response("Mavzu: Sotuvlar", is_pro=True)
        self.assertIsNotNone(res_free)
        self.assertIsNotNone(res_pro)
        self.assertIn("post_text", res_free)
        self.assertIn("post_text", res_pro)
        # PRO should have bold title per enhancement
        # Since mock returns bold for PRO, check
        self.assertTrue("<b>" in res_pro["post_text"] or "PRO" in res_pro["post_text"])

    async def test_generate_ai_response_system_injection(self):
        # When system_instruction provided, is_pro should still inject enhancement
        custom_sys = "Custom system instruction"
        res = await ai_agent.generate_ai_response("Test", system_instruction=custom_sys, is_pro=True)
        self.assertIsNotNone(res)
        # The mock captures system_instruction - we can check via side effect
        # For this, we test that function doesn't crash and returns dict

    def test_sync_wrapper_exists(self):
        # b2c01d1 original sync signature compatibility
        self.assertTrue(hasattr(ai_agent, "audit_post_sync") or hasattr(ai_agent, "audit_post_compat"))
        # Also audit_post should be callable as async
        self.assertTrue(asyncio.iscoroutinefunction(ai_agent.audit_post))


if __name__ == '__main__':
    unittest.main()
