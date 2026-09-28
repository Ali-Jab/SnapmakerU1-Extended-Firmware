"""Integration coverage for upstream metadata options and guarded recovery."""
import copy
import unittest
from unittest.mock import AsyncMock

from test_spoollink import FakeConfig, OLD_SPOOL, OLD_UID, SPOOLLINK


class CombinedMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def apply(self, generic=False, vendor="Bambu"):
        config = FakeConfig()
        config.options["force_generic_vendor"] = generic
        link = SPOOLLINK.SpoolLink(config)
        link._spoollink_set = AsyncMock(return_value={})
        spool = copy.deepcopy(OLD_SPOOL)
        spool["filament"]["vendor"]["name"] = vendor
        original = copy.deepcopy(spool)
        await link._apply_spool(2, spool, OLD_UID)
        info = link._spoollink_set.call_args.kwargs["info"]
        self.assertEqual(spool, original)
        self.assertEqual(link._known_spools[2], (OLD_UID, original))
        self.assertEqual(info["SPOOL_ID"], original["id"])
        self.assertEqual(info["CARD_UID"], [1, 2, 3, 4])
        return info, link

    async def test_generic_vendor_preserves_identity_and_cached_metadata(self):
        info, _ = await self.apply(True)
        self.assertEqual(info["VENDOR"], "Generic")
        self.assertEqual(info["SUB_TYPE"], "")

    async def test_default_mode_preserves_vendor_and_variant(self):
        info, _ = await self.apply()
        self.assertEqual(info["VENDOR"], "Bambu")
        self.assertEqual(info["SUB_TYPE"], "Tough+")

    async def test_snapmaker_is_exempt_from_generic_transformation(self):
        info, _ = await self.apply(True, "Snapmaker")
        self.assertEqual(info["VENDOR"], "Snapmaker")
        self.assertEqual(info["SUB_TYPE"], "Tough+")

    async def test_failed_apply_cannot_seed_recovery_cache(self):
        link = SPOOLLINK.SpoolLink(FakeConfig())
        link._spoollink_set = AsyncMock(return_value=None)
        result = await link._apply_spool(0, copy.deepcopy(OLD_SPOOL), OLD_UID)
        self.assertIsNone(result)
        self.assertNotIn(0, link._known_spools)

    async def test_missing_cache_does_not_restore_an_unknown_card(self):
        link = SPOOLLINK.SpoolLink(FakeConfig())
        link._spoollink_set = AsyncMock(return_value={})
        link._spoolman_find_by_card = AsyncMock(return_value=[])
        link._load_cache = lambda uid: None
        result = await link._resolve_spool(0, card_uid=OLD_UID)
        self.assertIsNone(result)
        self.assertNotIn(0, link._known_spools)
        self.assertTrue(all("info" not in c.kwargs for c in link._spoollink_set.call_args_list))
