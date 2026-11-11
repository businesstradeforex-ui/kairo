"""v1.2: learner, paper fills, archived reset, global model file."""
import json, os, tempfile, unittest

os.environ.setdefault("KAIRO_FX", "1.08")
os.environ.setdefault("KAIRO_ENV", "test")

import common
import fills
import learner
import paper
from ai_local import current_model


class LearnerTests(unittest.TestCase):
    def test_block_needs_many_losses(self):
        stats = {}
        key = learner.bucket({"setup": "score", "liq": 1000})
        for _ in range(learner.BLOCK_N):
            learner.update(stats, key, False)
        mult, _, status = learner.multiplier(stats, {"setup": "score", "liq": 1000})
        self.assertEqual(status, "block")
        self.assertEqual(mult, 0.0)

    def test_short_sample_does_not_block(self):
        stats = {}
        key = learner.bucket({"setup": "score", "liq": 1000})
        for _ in range(3):
            learner.update(stats, key, False)
        mult, _, status = learner.multiplier(stats, {"setup": "score", "liq": 1000})
        self.assertEqual(status, "watch")
        self.assertEqual(mult, 1.0)

    def test_journal_roundtrip(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "journal.jsonl")
        learner.journal_loss(path, {"setup": "score", "pnl_usd": -4})
        line = open(path, encoding="utf-8").read().strip()
        self.assertEqual(json.loads(line)["pnl_usd"], -4)


class QualityTests(unittest.TestCase):
    def test_sell_pressure_and_fading_volume(self):
        import quality
        self.assertEqual(quality.pressure_block({"m5": {"buys": 2, "sells": 9}}), "sell_pressure")
        self.assertIsNone(quality.pressure_block({"m5": {"buys": 9, "sells": 4}}))
        self.assertEqual(quality.velocity_block({"m5": 100, "h1": 40_000}), "volume_fading")
        self.assertIsNone(quality.velocity_block({"m5": 2_000, "h1": 20_000}))


class FillTests(unittest.TestCase):
    def test_buy_includes_priority_fee(self):
        q = fills.paper_buy(1.0, 100.0, 20_000)
        self.assertGreater(q["fill_price"], 1.0)
        self.assertEqual(q["priority_fee_usd"], fills.PRIORITY_FEE_USD)
        self.assertAlmostEqual(q["cost_usd"], 100.0 + fills.PRIORITY_FEE_USD)

    def test_size_stays_inside_the_cap(self):
        sized = fills.size_for_score(1000, 90, 0.02, 0.06)
        self.assertLessEqual(sized, 60.01)
        self.assertGreater(sized, 0)


class ResetTests(unittest.TestCase):
    def test_reset_archives_then_restarts(self):
        folder = tempfile.mkdtemp()
        common.bind_data_dir(folder)
        con = common.db()
        paper.ensure_session(con)
        con.execute(
            "INSERT INTO positions(mint,pair,symbol,status,entry_ts,entry_price,qty,cost_usd) VALUES(?,?,?,?,?,?,?,?)",
            ("m", "p", "X", "open", "t", 1, 1, 10),
        )
        con.commit()
        out = paper.reset(con, 500)
        self.assertTrue(os.path.isfile(out["archive"]))
        saved = json.load(open(out["archive"], encoding="utf-8"))
        self.assertEqual(saved["positions"][0]["symbol"], "X")
        left = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        self.assertEqual(left, 0)
        self.assertEqual(common.kv_get(con, "bankroll_eur"), 500.0)
        common.clear_data_dir()


class ModelPathTests(unittest.TestCase):
    def test_user_dir_reads_the_base_model_file(self):
        root = tempfile.mkdtemp()
        user = os.path.join(root, "users", "9")
        os.makedirs(user)
        with open(os.path.join(root, "model.txt"), "w", encoding="utf-8") as f:
            f.write("gemma4:12b\n")
        old = common.BASE
        common.BASE = root
        try:
            common.bind_data_dir(user)
            self.assertEqual(current_model(), "gemma4:12b")
        finally:
            common.clear_data_dir()
            common.BASE = old


if __name__ == "__main__":
    unittest.main()
