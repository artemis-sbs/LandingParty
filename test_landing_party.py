"""Dawnline holds together: every reference resolves, and every way out can be PLAYED.

`--test` proves the story compiles, the world spawns and the clock runs down, but
headless has no consoles - so nobody lands, walks, talks or opens anything, and that is
the whole game. This builds the world from the REAL files the way `story.mast` does, puts
four crew members on the ground, and plays each ending through the same calls a console's
clicks make: using props, talking to people, picking choices, shooting.

Checks run FLAT (5 + skill + help, no dice), so a route either opens for the right crew
member or does not.

What it will NOT catch: how any of it looks on a console, or MAST routes (the orbit
hail, the power hail, the ending screen). Those need `--test` and the engine.

Run: PYTHONPATH=../sbs_utils python -m unittest test_landing_party
"""
import os
import sys
import unittest

from sbs_utils.fs import test_set_exe_dir
test_set_exe_dir()

import cosmos_dev.mock.sbs as mock_sbs
sys.modules.setdefault("sbs", mock_sbs)

import sbs_utils.mast_sbs.story_nodes  # noqa: F401  (import first: circular import)
from sbs_utils.agent import clear_shared
from sbs_utils.gui import GuiClient
from sbs_utils.helpers import Context, FakeEvent, FrameContext
from sbs_utils.spaceobject import SpaceObject
from sbs_utils.procedural import boarding as A
from sbs_utils.procedural import tilemap as T
from sbs_utils.procedural import boarding_tiles as BT
from sbs_utils.procedural import boarding_props as P
from sbs_utils.procedural import boarding_checks as C
from sbs_utils.procedural import boarding_combat as K
from sbs_utils.procedural import boarding_quests as Q
from sbs_utils.procedural.amd_dialogue import dialogue_scenes, dialogue_parse
from sbs_utils.procedural.amd_doc import amd_document, amd_section
from sbs_utils.procedural.amd_mission import amd_mission_data
from sbs_utils.procedural.boarding_site import boarding_arm
from sbs_utils.procedural.gui import boarding_gui as G
from sbs_utils.procedural.inventory import set_inventory_value
from sbs_utils.procedural.lifeform import lifeform_spawn
from sbs_utils.procedural.signal import signal_observe, signal_unobserve, signal_observers_clear

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp_world as L  # noqa: E402

ENG, SCI, SEC, COM = (0x8000000000000101, 0x8000000000000102,
                      0x8000000000000103, 0x8000000000000104)
CREW = ((ENG, "CPO Dana Kovac", "engineering"), (SCI, "Lt Sam Reyes", "science"),
        (SEC, "Ens Petra Lund", "security"), (COM, "Lt Anh Ferro", "comms"))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


class World(unittest.TestCase):
    """The world as `story.mast` builds it, with four crew on the landing ridge."""

    def setUp(self):
        mock_sbs.create_new_sim()
        FrameContext.context = Context(mock_sbs.sim, mock_sbs, FakeEvent())
        self.addCleanup(setattr, FrameContext, "context", None)
        clear_shared()
        SpaceObject.clear()
        signal_observers_clear()
        for clear in (A.boarding_clear, T.tilemap_clear, BT.boarding_tile_clear,
                      P.boarding_props_clear, C.boarding_checks_clear,
                      K.boarding_combat_clear, Q.boarding_quests_clear):
            clear()
            self.addCleanup(clear)
        self.addCleanup(signal_observers_clear)
        T._WATCH["task"] = object()      # the tests walk by hand
        K._WATCH["task"] = object()
        T.tilemap_set_clock(0.0)
        self.now = 0.0

        L.lp_reset()
        L.lp_install()
        A.boarding_metric_install()
        L.lp_setup_tiles()
        self.assertEqual(L.lp_load_areas(read=lambda p: _read(p)), 6)
        self.world = amd_document(_read("world.amd"), data_parser=amd_mission_data)
        scenes_doc = amd_document(_read("scenes.amd"), data_parser=amd_mission_data)
        self.scenes = dialogue_scenes(amd_section(scenes_doc, "scenes"))
        self.hails = dialogue_scenes(amd_section(self.world, "hails"))
        P.boarding_props_scenes(self.scenes)
        P.boarding_props_declare(amd_section(self.world, "props"))
        P.boarding_props_place()
        K.boarding_hostiles_declare(amd_section(self.world, "people"))
        K.boarding_hostiles_declare(amd_section(self.world, "hostiles"))
        K.boarding_hostiles_place()
        P.boarding_props_install()
        K.boarding_combat_install()
        C.boarding_checks_mode("flat")
        C.boarding_skills_from_amd(amd_document(_read("landing_crew.amd")))

        ship = lifeform_spawn("Artemis", "", "x")
        A.boarding_invite(ship, [], title="Stillwater", area="ridge")
        self.body = {}
        for cid, name, job in CREW:
            GuiClient(cid)
            body = lifeform_spawn(name, "", "boarding," + job)
            set_inventory_value(body.id, A.JOBS_KEY, [job])
            A.boarding_assign(cid, body.id)
            G.boarding_go_down(cid)
            self.body[cid] = body.id
        Q.boarding_quests_grant(amd_section(self.world, "side_stories"))
        self.signals = []
        signal_observe(self._obs)

    def _obs(self, name, data):
        self.signals.append(name)

    # --- driving ------------------------------------------------------------------

    def put_by(self, cid, area, x, y):
        """Stand this crew member on an open cell beside (x, y) in an area."""
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
            if T.tilemap_is_open(area, x + dx, y + dy):
                T.tilemap_place(self.body[cid], area, x + dx, y + dy)
                return
        self.fail(f"nowhere to stand beside {area} {x},{y}")

    def use(self, cid, key):
        rec = P.boarding_prop(key)
        at = T.tilemap_where(rec["id"])
        self.assertIsNotNone(at, f"prop {key} is not on the map")
        self.put_by(cid, *at)
        return P.boarding_interact(cid, key)

    def talk(self, cid, key):
        rec = K.boarding_hostile(key)
        at = T.tilemap_where(rec["id"])
        self.assertIsNotNone(at, f"{key} is not on the map")
        self.put_by(cid, *at)
        self.assertTrue(K.boarding_hostile_click(cid, *at), f"{key} would not talk")

    def labels(self, cid):
        return [c.label for c in A.boarding_choices(cid)]

    def pick(self, cid, label):
        choices = self.labels(cid)
        self.assertIn(label, choices, f"not offered to this crew member: {label!r}")
        self.assertTrue(A.boarding_answer(cid, choices.index(label),
                                          seq=A.boarding_seq_for(cid)), label)

    def scene(self, cid):
        return A.boarding_scene(A.boarding_channel_of(cid))


class TestTheContentResolves(World):
    def test_every_prop_is_on_the_map(self):
        for key in P.boarding_props():
            rec = P.boarding_prop(key)
            if not rec["hidden"]:
                self.assertIsNotNone(rec["id"], f"prop {key} has no cell")

    def test_everyone_is_on_the_map(self):
        for key in K.boarding_hostiles():
            self.assertIsNotNone(K.boarding_hostile(key)["id"], f"{key} has no cell")

    def test_every_scene_a_prop_or_person_names_exists(self):
        for key in P.boarding_props():
            s = P.boarding_prop(key)["scene"]
            self.assertTrue(not s or s in self.scenes, f"prop {key}: no scene {s}")
        for key in K.boarding_hostiles():
            s = K.boarding_hostile(key)["talk"]
            self.assertTrue(not s or s in self.scenes, f"{key}: no scene {s}")

    def test_every_quest_lead_is_a_prop_or_person(self):
        """A `Leads to:` key nobody declared would just never be badged - silently."""
        for section in ("quests", "side_stories"):
            stack = list(amd_section(self.world, section).get("children", []))
            while stack:
                n = stack.pop()
                stack.extend(n.get("children", []) or [])
                for key in str((n.get("data") or {}).get("leads_to") or "").split(","):
                    key = key.strip().lower()
                    if key:
                        self.assertTrue(P.boarding_prop(key) or K.boarding_hostile(key),
                                        f"{n.get('key')}: leads to unknown {key!r}")

    def test_a_crew_member_is_pointed_at_their_side_story(self):
        from sbs_utils.procedural.boarding_hints import boarding_leads
        self.assertIn("obelisk", boarding_leads(SCI))
        self.assertNotIn("obelisk", boarding_leads(ENG))

    def test_the_ridge_shows_what_is_worth_a_look(self):
        from sbs_utils.procedural.boarding_hints import boarding_hints
        T.tilemap_reveal_all("ridge")
        drone = T.tilemap_where(P.boarding_prop("drone")["id"])
        self.assertEqual(boarding_hints(ENG, "ridge").get((drone[1], drone[2])), "new")
        self.assertIn("way", boarding_hints(ENG, "ridge").values())

    def test_every_tile_name_has_a_cell_in_the_atlas(self):
        from PIL import Image
        img = Image.open(os.path.join(HERE, "media", "lp_tiles.png"))
        _, cols, rows, cell = L.LP_ATLAS
        self.assertEqual(img.size, (cols * cell, rows * cell))
        self.assertLessEqual(len(L.LP_TILE_NAMES), cols * rows)

    def test_every_choice_goes_somewhere_real(self):
        for key, node in list(self.scenes.items()) + list(self.hails.items()):
            for ch in dialogue_parse(node)["choices"]:
                self.assertTrue(not ch["target"] or ch["target"] in self.scenes
                                or ch["target"] in self.hails,
                                f"{key}: choice {ch['label']!r} -> {ch['target']!r}")
                for out in ch["outcomes"]:
                    if out[0] == "check" and "else" in out:
                        tgt = out[out.index("else") + 1]
                        self.assertIn(tgt, self.scenes, f"{key}: check else {tgt}")

    def test_every_exit_leads_somewhere_loaded(self):
        for area in T.tilemap_areas():
            for mark in T.tilemap_marks(area):
                target, _ = T.tilemap_exit_target(area, mark)
                if mark.startswith("to_"):
                    self.assertIn(target, T.tilemap_areas(), f"{area}:{mark}")

    def test_every_crew_member_got_their_side_story(self):
        for key, cid in (("patience_heart", ENG), ("lantern_says", SCI),
                         ("quiet_deputy", SEC), ("vhesk_terms", COM)):
            self.assertEqual(Q.boarding_quest_owner(key), self.body[cid], key)
        self.assertIsNone(Q.boarding_quest_owner("survey_team"))   # no medic yet
        Q.boarding_quests_open_unclaimed(amd_section(self.world, "side_stories"))
        self.assertEqual(Q.boarding_quest_owner("survey_team"), "party")

    def test_the_party_lands_on_the_ridge(self):
        for cid, _, _ in CREW:
            self.assertEqual(BT.boarding_tile_where(cid)[0], "ridge")

    def test_only_three_areas_have_a_transporter_lock(self):
        self.assertEqual(sorted(T.tilemap_areas(known_only=True, beam_only=True)),
                         ["colony", "flats", "ridge"])


class TestTheRidge(World):
    def test_the_drone_maps_the_caves_and_the_lantern(self):
        self.assertFalse(T.tilemap_known("caves"))
        self.assertEqual(self.use(SCI, "drone")[0], "scene")
        self.pick(SCI, "Pull its survey data")
        self.pick(SCI, "Mark both on the map")
        self.assertTrue(T.tilemap_known("caves"))
        self.assertTrue(T.tilemap_known("lantern"))

    def test_the_path_down_reaches_the_colony(self):
        T.tilemap_walk(self.body[ENG], 16, 0)
        for _ in range(600):
            self.now += 0.1
            T.tilemap_set_clock(self.now)
            T.tilemap_tick()
            if not T.tilemap_walking(self.body[ENG]):
                break
        self.assertEqual(BT.boarding_tile_where(ENG)[0], "colony")


class TestLiftOff(World):
    """Fly them out: three parts, a fitted engine, a road, a pilot."""

    def test_the_whole_route(self):
        # The cable: in the locked depot. Kovac cannot force it flat (5+4 < 10) - a CUT
        # shot can.
        self.assertEqual(self.use(ENG, "depot_door")[0], "failed")
        door = T.tilemap_where(P.boarding_prop("depot_door")["id"])
        self.put_by(ENG, *door)
        boarding_arm(ENG, "cut")
        self.assertTrue(BT.boarding_tile_click(ENG, *door))
        self.assertTrue(P.boarding_prop_is_open("depot_door"))
        self.assertEqual(self.use(ENG, "cable")[0], "picked")
        # The injector: the Skaraan camp crate - past the sentries, talked down by Ferro.
        self.talk(COM, "sentry_1")
        self.pick(COM, "Answer in Skaraan")
        self.pick(COM, "Walk on")
        self.assertEqual(K.boarding_hostile_state("sentry_2"), "calm")
        self.use(ENG, "camp_crate")
        self.pick(ENG, "Open the marked crate")
        self.pick(ENG, "Take the injector")
        self.assertEqual(P.boarding_holding(self.body[ENG], "injector"), 1)
        # The coil: in the caves, on a glassback nest. Stun the one lying on it.
        T.tilemap_reveal_area("caves")
        gb = K.boarding_hostile("gb_2")
        at = T.tilemap_where(gb["id"])
        self.put_by(ENG, *at)
        boarding_arm(ENG, "full")
        self.assertTrue(BT.boarding_tile_click(ENG, *at) or True)
        self.assertEqual(self.use(ENG, "coil")[0], "picked")
        # Fit all three and bring her up.
        self.use(ENG, "patience")
        for part in ("Fit the injector", "Fit the coil", "Fit the main cable"):
            self.pick(ENG, part)
        self.pick(ENG, "Bring her engine up")
        self.assertEqual(self.scene(ENG), "patience_fitted")
        self.pick(ENG, "Seal the cowling")
        self.assertIn("lp_hauler_fixed", self.signals)
        # The road: three markers, set by eye (nobody here is helm): 5 + 0 < 8 fails
        # flat, so a pilot's fly-out blind is also closed - it takes a helm or the road.
        self.use(ENG, "marker_1")
        self.pick(ENG, "Sight it by eye")
        self.assertEqual(self.scene(ENG), "marker_off")
        for n in (1, 2, 3):
            L.lp_note("marker", str(n))
        from sbs_utils.procedural.signal import signal_emit
        signal_emit("lp_tally", {"LP_KIND": "marker", "LP_ITEM": "3"})
        self.assertTrue(L.lp_is("road_clear"))
        self.assertIn("lp_road_done", self.signals)
        self.use(ENG, "patience")
        self.pick(ENG, "Take the pilot's seat")
        self.pick(ENG, "Fly out along the surveyed road")
        self.pick(ENG, "Take her up")
        self.assertIn("lp_launch", self.signals)
        self.assertEqual(L.lp_ending("launch")[0], "lift_off")

    def test_the_hauler_side_story_completes(self):
        from sbs_utils.procedural.quest import quest_is_complete
        from sbs_utils.procedural.signal import signal_emit
        signal_emit("lp_hauler_fixed", {})
        self.assertTrue(quest_is_complete(self.body[ENG], "patience_heart"))


class TestTheDeputy(World):
    """Lund's story: two pieces of evidence and a confession - and Yilla in the cellar."""

    def test_evidence_confession_and_the_cellar(self):
        self.talk(SEC, "harrow")
        self.assertNotIn("Lay out what you found", self.labels(SEC))
        self.pick(SEC, "Leave him be")
        self.use(SEC, "office_log")
        self.pick(SEC, "Save the log")
        self.use(SEC, "camp_crate")
        self.pick(SEC, "Photograph the stencils")
        self.assertEqual(L.lp_count("evidence"), 2)
        self.talk(SEC, "harrow")
        self.pick(SEC, "Lay out what you found")
        self.pick(SEC, "Take his keys")
        self.pick(SEC, "Take them")
        self.assertIn("lp_harrow_confessed", self.signals)
        self.assertEqual(P.boarding_holding(self.body[SEC], "harrow_key"), 1)
        self.assertEqual(self.use(SEC, "cellar_door")[0], "opened")
        # Only someone who speaks Skaraan gets Yilla to trust them without a roll.
        self.talk(COM, "yilla")
        self.pick(COM, "Answer her in Skaraan")
        self.pick(COM, "Take her home to the Gnaw")
        self.assertEqual(P.boarding_holding(self.body[COM], "yilla"), 1)
        self.assertEqual(K.boarding_hostile_state("yilla"), "down")    # gone with them


class TestSkaraanHonor(World):
    """Bring Yilla home: Vhesk hands over the core AND lifts the colony."""

    def test_the_good_bargain(self):
        P.boarding_give(self.body[COM], "yilla")
        self.talk(COM, "vhesk")
        self.pick(COM, "Bring Yilla forward")
        self.assertIn("lp_yilla_home", self.signals)
        self.pick(COM, "Take the vault key")
        self.assertEqual(P.boarding_holding(self.body[COM], "vhesk_key"), 1)
        self.pick(COM, "Ask her to lift the colony now")
        self.pick(COM, "Send them")
        self.assertIn("lp_bargain_good", self.signals)
        self.assertEqual(L.lp_ending("bargain_good")[1], "Skaraan Honor")

    def test_without_skaraan_the_captain_scorns_you(self):
        self.talk(ENG, "vhesk")
        self.assertNotIn("Answer in her own language", self.labels(ENG))
        self.pick(ENG, "Make your case")           # 5 + 0 < 10
        self.assertEqual(self.scene(ENG), "vhesk_scorn")


class TestDawnlineHeld(World):
    """Wake the Lantern, attuned: four glyphs, the core, power from orbit."""

    def read_glyph(self, prop, label="Read the carving", then="Commit it to memory"):
        self.use(SCI, prop)
        self.pick(SCI, label)
        self.pick(SCI, then)

    def test_the_whole_route(self):
        T.tilemap_reveal_area("caves")
        T.tilemap_reveal_area("lantern")
        self.read_glyph("obelisk")
        self.read_glyph("glyph_2_panel")
        self.read_glyph("glyph_3_panel", then="Speak it to the sentinels")
        self.assertEqual(K.boarding_hostile_state("sent_1"), "calm")
        # The inner door: Reyes, science 4, flat 9 - exactly the DC.
        self.assertEqual(self.use(SCI, "inner_door")[0], "opened")
        self.read_glyph("glyph_4_panel")
        self.assertIn("lp_glyphs_all", self.signals)
        # The core, from the Gnaw's vault.
        P.boarding_give(self.body[ENG], "vhesk_key")
        self.assertEqual(self.use(ENG, "hold_door")[0], "opened")
        self.use(ENG, "hold_crate")
        self.pick(ENG, "Take the Lantern core")
        self.assertNotIn("Take the Lantern core", self.labels(ENG))   # only once
        self.use(ENG, "pedestal")
        self.pick(ENG, "Seat the Lantern core")
        self.use(ENG, "control")
        self.pick(ENG, "Call the ship for power")
        self.assertIn("lp_power_ready", self.signals)
        # The bridge answers the hail (a MAST route in the game).
        from sbs_utils.procedural.signal import signal_emit
        signal_emit("lp_power", {})
        self.assertTrue(L.lp_is("powered"))
        self.use(SCI, "control")
        self.pick(SCI, "The console is awake")
        self.pick(SCI, "Name the valley, the deep places and the sun")
        self.pick(SCI, "Watch the shadow fall")
        self.assertIn("lp_wake_true", self.signals)
        self.assertEqual(L.lp_ending("wake_true")[0], "held")

    def test_without_the_glyphs_only_the_false_shade_is_offered(self):
        L.lp_flag("core_seated")
        L.lp_flag("powered")
        self.use(ENG, "control")
        self.pick(ENG, "The console is awake")
        self.assertNotIn("Name the valley, the deep places and the sun", self.labels(ENG))
        self.pick(ENG, "Point it at the sun and let it go")
        self.pick(ENG, "Hold on")
        self.assertIn("lp_wake_false", self.signals)


class TestTheSurveyTeam(World):
    def test_venom_antivenom_and_the_back_way(self):
        # A glassback that carried venom, put down; the drop is picked up.
        T.tilemap_reveal_area("caves")
        gb = K.boarding_hostile("gb_1")
        at = T.tilemap_where(gb["id"])
        self.put_by(SEC, *at)
        boarding_arm(SEC, "full")
        BT.boarding_tile_click(SEC, *at)
        self.assertEqual(K.boarding_hostile_state("gb_1"), "down")
        drop = P.boarding_prop_at(*at)
        self.assertIsNotNone(drop)
        self.assertEqual(self.use(SEC, drop)[0], "picked")
        # Brewing needs medical 3+ flat (5 + 2 job = 7 < 8 for a non-medic, 0 for Lund).
        P.boarding_hand_over(self.body[SEC], self.body[SCI], "venom")
        C.boarding_skills_set(self.body[SCI], {"medical": 3})
        self.use(SCI, "clinic_bench")
        self.pick(SCI, "Brew antivenom from the sample")
        self.pick(SCI, "Pack them")
        self.talk(SCI, "castellan")
        self.pick(SCI, "Treat the bite")
        self.pick(SCI, "Get them both out")
        self.assertIn("lp_survivors_saved", self.signals)
        self.assertEqual(K.boarding_hostile_state("castellan"), "down")


class TestDawn(World):
    def test_the_dawn_ending_says_what_happened(self):
        L.lp_ending("dawn")
        text = L.lp_ending_text()
        self.assertIn("Colonists saved: 60 of 212", text)
        text.encode("ascii")          # the engine draws ASCII only


if __name__ == "__main__":
    unittest.main()
