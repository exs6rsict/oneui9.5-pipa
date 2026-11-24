"""Policy-level permissive: every resolved domain type becomes permissive in the compiled binary."""
import os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sepolicy_permissive as sp

BASE = """
(class process (transition fork))
(class file (read))
(classorder (process file))
(sid kernel)
(sidorder (kernel))
(mls true)
(sensitivity s0)
(sensitivityorder (s0))
(category c0)
(categoryorder (c0))
(sensitivitycategory s0 (c0))
(level lo (s0))
(levelrange lr (lo lo))
(user u)
(role r)
(role object_r)
(userrole u r)
(userrole u object_r)
(userlevel u lo)
(userrange u lr)
(sidcontext kernel (u r kernel_d lr))
(typeattribute domain)
(typeattribute coredomain)
(type kernel_d)
(type app_d)
(type file_t)
(roletype r kernel_d)
(roletype r app_d)
(roletype object_r file_t)
(typeattributeset coredomain (kernel_d))
(typeattributeset domain (coredomain app_d))
(allow app_d file_t (file (read)))
"""
RULES = "(expandtypeattribute (domain) false)\n(allow domain self (process (fork)))\n"  # real policy uses `domain`, so the binary keeps it


@unittest.skipUnless(all(shutil.which(t) for t in ("secilc", "checkpolicy")), "secilc/checkpolicy missing")
class PermissiveTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def write(self, name, text):
        path = os.path.join(self.d, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_every_domain_incl_nested_attributes_is_permissive_and_nothing_else(self):
        base = self.write("base.cil", BASE + RULES)
        r = sp.make_permissive([base], os.path.join(self.d, "permissive.cil"), self.d)
        self.assertEqual(r["domains"], ["app_d", "kernel_d"])
        self.assertEqual(r["permissive_in_binary"], ["app_d", "kernel_d"])
        self.assertEqual(r["base_permissive"], [])

    def test_permissive_does_not_rescue_a_policy_that_fails_to_compile(self):
        broken = self.write("broken.cil", BASE + RULES + "(allow app_d undefined_t (file (read)))\n")
        with self.assertRaisesRegex(RuntimeError, "secilc"):
            sp.make_permissive([broken], os.path.join(self.d, "permissive.cil"), self.d)

    def test_refuses_when_domain_attribute_did_not_survive_into_the_binary(self):
        base = self.write("base.cil", BASE)  # no rule uses `domain`: secilc drops it
        with self.assertRaisesRegex(RuntimeError, "no domain types"):
            sp.make_permissive([base], os.path.join(self.d, "permissive.cil"), self.d)
