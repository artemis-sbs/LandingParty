"""Dawnline - the mission's own vocabulary on top of the library's ground layer.

Everything generic (tile areas, walking, props, checks, hostiles, quests, the xESS) is
sbs_utils. This file is only what is Mereth's: the tileset, the story's running tally,
and how the ending is decided. Every public function is prefixed `lp_` - they become
MAST globals in one flat, mission-wide namespace.

THE TALLY. Scenes record what the party has done with the `lp` outcome verb and ask
about it with the `lp` guard word, so the story state lives in the AMD rather than in a
signal-and-route per fact::

    - [Read the glyphs](glyph_1_read) if science ; lp glyph 1
    - [Wake it, attuned](lantern_attuned) if lp glyph >= 4

Kinds used: `glyph`, `evidence`, `marker`, `flag`. `lp flag <name>` is a one-off fact.
"""
from sbs_utils.agent import Agent

# The atlas layout, in the order `_tools/make_tiles.py` draws it. Change both together.
LP_TILE_NAMES = [
    "dust", "scrub", "salt", "path", "floor", "deck", "cave", "glyphfloor",
    "rock", "cliff", "brine", "crystal", "wall", "pwall", "hull", "vent",
    "crew", "colonist", "skaraan", "glassback", "sentinel", "vhesk", "youngster", "survivor",
    "drone", "crate", "hauler", "door_shut", "door_open", "rockfall", "panel", "terminal",
    "marker", "marker_set", "tent", "beacon", "pedestal", "pedestal_lit", "part", "key",
    "medkit", "datapad", "bones", "drop", "sample", "console", "bed", "heat",
    "exit",
]

# kind -> (walk, see). A kind you can see across but not walk (brine, a cliff edge) is
# what makes a map readable: the far bank is visible, getting there is the puzzle.
_KINDS = {
    "dust": (True, True), "scrub": (True, True), "salt": (True, True),
    "path": (True, True), "floor": (True, True), "deck": (True, True),
    "cave": (True, True), "glyphfloor": (True, True), "vent": (True, True),
    "rock": (False, False), "cliff": (False, True), "brine": (False, True),
    "crystal": (False, False), "wall": (False, False), "pwall": (False, False),
    "hull": (False, False),
    # A way out, drawn as one: bright chevrons, so nobody has to guess where it is.
    "exit": (True, True),
}

LP_AREAS = ["ridge", "colony", "flats", "caves", "lantern", "gnaw"]
LP_COLONISTS = 212
LP_SHIP_LIFT = 60      # what the bridge alone can beam out before the dawn

_STATE = {"tally": {}, "ending": None}


def lp_setup_tiles():
    """Register the atlas cells and the tileset. Call once, before loading areas."""
    from sbs_utils.procedural.gui.image import gui_image_add_atlas_grid
    from sbs_utils.procedural.tilemap import tilemap_tileset
    from sbs_utils.procedural.boarding_tiles import boarding_tile_style
    from sbs_utils.procedural.boarding_combat import boarding_drop_sprite
    gui_image_add_atlas_grid("media/lp_tiles", 8, 8,
                             ["lp:" + n for n in LP_TILE_NAMES], cell=64)
    tilemap_tileset("mereth", {k: {"cell": "lp:" + k, "walk": w, "see": s}
                               for k, (w, s) in _KINDS.items()})
    boarding_tile_style(sprite="lp:crew",
                        colors=["#4cf", "#fc4", "#f66", "#8f8", "#c8f", "#fa8"])
    boarding_drop_sprite("lp:drop")


def lp_load_areas(read=None):
    """Load every area file. Returns how many loaded - six, or something is wrong."""
    from sbs_utils.procedural.tilemap import tilemap_load
    if read is None:
        from sbs_utils.procedural.media import media_read_relative_file as read
    n = 0
    for key in LP_AREAS:
        if tilemap_load(read("surface/%s.tiles" % key)):
            n += 1
    return n


# --- the tally -------------------------------------------------------------------------

def lp_note(kind, item="1"):
    """Record something the party did. Returns how many of that kind there are now."""
    kind = str(kind).strip().lower()
    got = _STATE["tally"].setdefault(kind, set())
    got.add(str(item).strip().lower())
    return len(got)


def lp_count(kind):
    return len(_STATE["tally"].get(str(kind).strip().lower(), set()))


def lp_has(kind, item):
    return str(item).strip().lower() in _STATE["tally"].get(str(kind).strip().lower(), set())


def lp_flag(name):
    return lp_note("flag", name)


def lp_is(name):
    """Whether a one-off fact is true: `lp_is("hauler_fixed")`."""
    return lp_has("flag", name)


def _lp_outcome(agent_id, speaker, tokens):
    if tokens:
        lp_note(tokens[0], tokens[1] if len(tokens) > 1 else "1")
        from sbs_utils.procedural.signal import signal_emit
        signal_emit("lp_tally", {"LP_KIND": str(tokens[0]).lower(),
                                 "LP_ITEM": str(tokens[1]).lower() if len(tokens) > 1 else "1"})
    return None


def _lp_metric(rest, agent_id):
    """`lp glyph` -> how many glyphs; `lp flag core_seated` -> 0 or 1."""
    bits = rest.split()
    if len(bits) >= 2 and bits[0] == "flag":
        return 1 if lp_is(bits[1]) else 0
    return lp_count(bits[0]) if bits else 0


def lp_install():
    """The `lp` outcome verb and guard word, and quests that hear `lp_*` signals.
    Idempotent."""
    from sbs_utils.procedural.amd_dialogue import dialogue_register_outcome
    from sbs_utils.procedural.boarding import boarding_metric_word
    from sbs_utils.procedural.signal import signal_observe
    dialogue_register_outcome("lp", _lp_outcome)
    boarding_metric_word("lp", _lp_metric)
    signal_observe(_lp_quest_signal)


def _lp_quest_signal(name, data):
    """Every `lp_*` signal, as it is emitted.

    A scene's `signal lp_x` is a quest milestone (`When: signal lp_x`), and the quest
    driver listens only to `quest_signal`, so each is passed on. The tally's MILESTONES
    are decided here too rather than in a MAST route, so the content tests - which run
    no MAST - exercise the same code the game does.
    """
    from sbs_utils.procedural.signal import signal_emit
    name = str(name)
    if not name.startswith("lp_"):
        return
    if name == "lp_tally":
        kind = (data or {}).get("LP_KIND")
        if kind == "glyph" and lp_count("glyph") >= 4 and not lp_is("glyphs_all"):
            lp_flag("glyphs_all")
            signal_emit("lp_glyphs_all", {})
        if kind == "marker" and lp_count("marker") >= 3 and not lp_is("road_done"):
            lp_flag("road_done")
            signal_emit("lp_road_done", {})
        if lp_is("hauler_fixed") and lp_count("marker") >= 3:
            lp_flag("road_clear")
        return
    if name == "lp_power" and not lp_is("powered"):
        from sbs_utils.procedural.boarding_props import boarding_props_signal
        from sbs_utils.procedural.messages import message_send
        lp_flag("powered")
        boarding_props_signal("lp_power")
        message_send("Power from orbit. The Lantern is awake and waiting at its control.",
                     to="boarding", kind="alert", sender="The Lantern")
    from sbs_utils.procedural.quest_driver import quest_on_signal
    quest_on_signal(name)


def lp_grant_story(section):
    """The whole crew's story, granted to the game itself."""
    from sbs_utils.procedural.quest_driver import quest_grant_amd
    quest_grant_amd(Agent.SHARED_ID, section)


def lp_reveal_ways():
    """The magistrate has laid out the three ways; show them in everyone's log."""
    from sbs_utils.procedural.quest import quest_set_state, QuestState
    for way in ("way_patience", "way_lantern", "way_gnaw"):
        quest_set_state(Agent.SHARED_ID, "dawnline_arc/" + way, QuestState.ACTIVE)


def lp_reset():
    """A new game: nothing done yet. Called from the map body, not at import."""
    _STATE["tally"] = {}
    _STATE["ending"] = None


# --- the ending ------------------------------------------------------------------------

def lp_ending(trigger):
    """Decide the ending from what triggered it and everything the party did.

    Returns `(key, title, text, saved)`. Recorded, so asking twice gives one answer.
    """
    if _STATE["ending"] is not None:
        return _STATE["ending"]
    glyphs = lp_count("glyph")
    lantern = "dark"
    saved = 0
    if trigger == "wake_true":
        key, title = "held", "Dawnline Held"
        saved, lantern = LP_COLONISTS, "restored"
        text = ("The Lantern turns its face to the sun, and the canyon stays in shadow. "
                "Stillwater keeps its fields, its homes and its two hundred and twelve "
                "people, and the thing on the ridge is doing what it was built to do.")
    elif trigger == "wake_false":
        key, title = "false_shade", "False Shade"
        saved, lantern = LP_COLONISTS, "misread"
        text = ("The Lantern wakes without being asked the right question. The valley goes "
                "dark and cool - and the caves below it do not. Stillwater lives. Whatever "
                "the Lantern was guarding in the deep places, it is guarding it badly now.")
    elif trigger == "launch":
        key, title = "lift_off", "Lift-off"
        saved = LP_COLONISTS
        lantern = "taken" if not lp_is("core_returned") else "dark"
        text = ("The Patience climbs out of the canyon ninety seconds ahead of the light, "
                "every seat full. Behind her Stillwater goes gold, then white.")
    elif trigger == "bargain_good":
        key, title = "bargain", "Skaraan Honor"
        saved, lantern = LP_COLONISTS, "dark"
        text = ("Vhesk keeps her word the way she keeps everything: exactly. Yilla goes home "
                "to the Gnaw, the colony goes up its ramp, and the Lantern's core stays where "
                "it belongs - dark, but there.")
    elif trigger == "bargain_core":
        key, title = "bargain", "Skaraan Bargain"
        saved, lantern = LP_COLONISTS, "sold"
        text = ("The Gnaw lifts with two hundred and twelve colonists in her holds and the "
                "Lantern's heart in her vault. Everyone lives. Nobody will ever know what the "
                "Lantern was.")
    else:
        key, title = "dawn", "Dawn"
        saved = LP_SHIP_LIFT
        text = ("The Dawnline reaches Stillwater. The transporter runs until the pattern "
                "buffers smoke. Sixty people come up. The rest of the story ends in light.")
    sides = [k for k in ("patience_heart", "lantern_says", "quiet_deputy", "vhesk_terms",
                         "salt_road", "survey_team") if _quest_done(k)]
    _STATE["ending"] = (key, title, text, saved, lantern, glyphs, sides)
    return _STATE["ending"]


def _quest_done(key):
    from sbs_utils.procedural.boarding_quests import boarding_quest_owner
    from sbs_utils.procedural.quest import quest_is_complete
    owner = boarding_quest_owner(key)
    if owner is None:
        return False
    holder = Agent.SHARED_ID if owner == "party" else owner
    return bool(quest_is_complete(holder, key))


def lp_ending_text():
    """The results screen text for the recorded ending (ASCII only - the engine draws it)."""
    if _STATE["ending"] is None:
        return ""
    key, title, text, saved, lantern, glyphs, sides = _STATE["ending"]
    lines = [title.upper(), "", text, "",
             "Colonists saved: %d of %d" % (saved, LP_COLONISTS),
             "The Lantern: %s" % lantern,
             "Glyphs read: %d of 4" % glyphs,
             "Side stories finished: %d" % len(sides)]
    return "\n".join(lines)


def lp_ending_key():
    return _STATE["ending"][0] if _STATE["ending"] else None
