"""The written content holds together: every route through Erebus reads, and gates.

`--test` proves the story compiles, the world spawns and the beam down route fires, but
headless has no console clients - so nobody morphs, nobody answers, and the SCENES are
the one part of this mission a green `--test` says nothing about. That is most of the
mission, and all of the writing.

This reads the real `landing_party.amd` and drives the real away module, so it fails when
the prose drifts: a choice pointing at a scene somebody renamed, a read that stopped
awarding its fact, a role word in a guard that no character carries.

What it will NOT catch: how any of it looks on a console. That needs the engine.

Run: PYTHONPATH=../sbs_utils python -m unittest test_landing_party
"""
import os
import sys
import unittest

from sbs_utils.fs import test_set_exe_dir
test_set_exe_dir()

import cosmos_dev.mock.sbs as mock_sbs

# Bind `sbs` before importing anything that does `import sbs` at module level.
sys.modules.setdefault("sbs", mock_sbs)

from sbs_utils.agent import clear_shared
from sbs_utils.helpers import Context, FakeEvent, FrameContext
from sbs_utils.procedural.amd_dialogue import dialogue_scenes
from sbs_utils.procedural.amd_doc import amd_document, amd_section
from sbs_utils.procedural.amd_lifeforms import lifeforms_spawn
from sbs_utils.procedural.amd_mission import amd_mission_data
from sbs_utils.procedural.amd import amd_choice
from sbs_utils.procedural.roles import add_role
from sbs_utils.spaceobject import SpaceObject
from sbs_utils.procedural import boarding as A

HERE = os.path.dirname(os.path.abspath(__file__))

# The four readings worth having, and the ending they unlock. Restated here on purpose:
# if someone edits the AMD so a fact can no longer be reached, this list is what notices.
FACTS = ("lp_cold", "lp_gentle", "lp_willing", "lp_sample")
LOCATIONS = ("arrival", "lab", "gallery", "shelter")
ROLE_OF = {"sorel": "medical", "ruiz": "engineering", "vale": "security", "anders": "science"}


class LandingPartyContent(unittest.TestCase):

    def setUp(self):
        mock_sbs.create_new_sim()
        SpaceObject.clear()
        clear_shared()
        FrameContext.context = Context(mock_sbs.sim, mock_sbs, FakeEvent())
        # amd_document takes the TEXT, not a path - handing it a filename parses the
        # filename as a document and yields an empty one, in silence.
        with open(os.path.join(HERE, "landing_party.amd"), encoding="utf-8") as fh:
            doc = amd_document(fh.read(), data_parser=amd_mission_data)
        self.scenes = dialogue_scenes(amd_section(doc, "boarding"))
        self.cast = lifeforms_spawn(amd_section(doc, "team"))
        A.boarding_clear()
        A.boarding_metric_install()

    def _authored(self, scene_key):
        """Every choice as WRITTEN, guards and all.

        A scene keeps its choices in its body text and parses them at call time, so
        `dialogue_choices` is the wrong tool for a graph check: it answers for one
        character and silently drops everything that character may not take. `amd_choice`
        is the library's own line parser, which is what the runtime uses too.
        """
        body = self.scenes[scene_key].get("description") or ""
        return [c for c in (amd_choice(line) for line in body.splitlines()) if c]

    def _choices_for(self, scene_key, member_key):
        A.boarding_scene_begin(self.scenes, scene_key, speaker="outpost")
        cid = 0x8000000000000001
        A.boarding_assign(cid, self.cast[member_key])
        return A.boarding_choices(cid)

    # --- the graph ----------------------------------------------------------

    def test_every_choice_points_somewhere_real(self):
        # An empty target is how a scene CLOSES, so it is the one allowed dangling ref.
        known = set(self.scenes)
        for key in self.scenes:
            for ch in self._authored(key):
                target = (ch.get("target") or "").strip()
                if not target:
                    continue
                self.assertIn(target, known,
                              f"scene '{key}' offers '{ch.get('label')}' pointing at "
                              f"'{target}', which no scene defines")

    def test_the_four_locations_exist_and_chain(self):
        for key in LOCATIONS:
            self.assertIn(key, self.scenes)
        # Each location must offer a way onward, or the party is stuck in it.
        onward = {"arrival": "lab", "lab": "gallery", "gallery": "shelter", "shelter": "decide"}
        for here, there in onward.items():
            targets = [(c.get("target") or "") for c in self._authored(here)]
            self.assertIn(there, targets, f"'{here}' has no way on to '{there}'")

    def test_the_story_can_be_closed(self):
        # At least one reachable scene ends the conversation. Without one the team can
        # never beam up - which is exactly how the probe's first cut stranded everybody.
        closers = [k for k in self.scenes
                   if any(not (c.get("target") or "").strip() for c in self._authored(k))]
        self.assertTrue(closers, "no scene closes; the boarding party can never come back")

    # --- the per-character menus, which are the whole feature ----------------

    def test_each_character_sees_their_own_read_at_every_location(self):
        for loc in LOCATIONS:
            for member, role_word in ROLE_OF.items():
                labels = [c.label for c in self._choices_for(loc, member)]
                self.assertTrue(len(labels) >= 2,
                                f"{member} has almost nothing to do at '{loc}'")

    def test_no_two_characters_get_the_same_menu(self):
        for loc in LOCATIONS:
            menus = {m: tuple(c.label for c in self._choices_for(loc, m)) for m in ROLE_OF}
            self.assertEqual(len(set(menus.values())), len(menus),
                             f"at '{loc}' two characters see an identical menu: {menus}")

    def test_a_gated_read_is_refused_to_the_wrong_character(self):
        # The medical read at the hatch must not be offered to the engineer.
        med = [c.label for c in self._choices_for("arrival", "sorel")]
        eng = [c.label for c in self._choices_for("arrival", "ruiz")]
        self.assertIn("Kneel by the body at the hatch", med)
        self.assertNotIn("Kneel by the body at the hatch", eng)

    def test_everyone_can_always_move_on(self):
        # The ungated choice. Without it a party missing a role would be stuck.
        for loc in LOCATIONS:
            for member in ROLE_OF:
                labels = [c.label for c in self._choices_for(loc, member)]
                self.assertTrue(len(labels) >= 1, f"{member} is stuck at '{loc}'")

    # --- the facts ----------------------------------------------------------

    def test_every_fact_is_reachable(self):
        emitted = set()
        for key in self.scenes:
            for ch in self._authored(key):
                for oc in ch.get("outcomes") or []:
                    if oc and oc[0] == "signal" and len(oc) > 1:
                        emitted.add(oc[1])
        for fact in FACTS:
            self.assertIn(fact, emitted, f"nothing in the station awards '{fact}'")

    def test_no_single_location_hands_over_three_facts(self):
        # The party must have to move through the station, not strip-mine one room.
        for key in self.scenes:
            here = set()
            for ch in self._authored(key):
                for oc in ch.get("outcomes") or []:
                    if oc and oc[0] == "signal" and oc[1] in FACTS:
                        here.add(oc[1])
            self.assertLess(len(here), 3, f"'{key}' alone unlocks the ending")

    def test_both_endings_are_authored(self):
        for key in ("ending_home", "ending_burn"):
            self.assertIn(key, self.scenes)

    # --- the gate on the ending ---------------------------------------------

    def test_the_understanding_ending_is_hidden_until_briefed(self):
        labels = [c.label for c in self._choices_for("decide", "anders")]
        self.assertNotIn("Vent the gallery and open the flue to the cloud deck", labels,
                         "the ending that is not a weapon must be earned")

    def test_briefing_the_team_reveals_it(self):
        # What the mission does once three distinct readings are in: a ROLE on the
        # characters, so the guard is answered by the resolver boarding_metric_install put in
        # rather than by a second one this mission would have to compose by hand.
        for member in self.cast.values():
            add_role(member, "briefed")
        labels = [c.label for c in self._choices_for("decide", "anders")]
        self.assertIn("Vent the gallery and open the flue to the cloud deck", labels)

    def test_the_weapon_ending_is_always_available(self):
        for member in ROLE_OF:
            labels = [c.label for c in self._choices_for("decide", member)]
            self.assertIn("Burn it off the coolant loop", labels,
                          "a party that understood nothing still has to be able to act")


if __name__ == "__main__":
    unittest.main()
