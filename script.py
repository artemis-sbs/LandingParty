try:
    # `import sbslibs` puts the declared sbslib/mastlibs on sys.path, and importing
    # handlerhooks is what defines `cosmos_event_handler` - the ONE function the engine
    # calls. Without both, the engine has no handler to call and the mission silently
    # does nothing at all: no compile log, no runtime log, no error.
    import sbslibs
    from sbs_utils.handlerhooks import *
    from sbs_utils.gui import Gui
    from sbs_utils.mast.maststorypage import StoryPage

    class LandingPartyPage(StoryPage):
        story_file = "story.mast"

    Gui.server_start_page_class(LandingPartyPage)
    Gui.client_start_page_class(LandingPartyPage)
except Exception as e:
    # Put the failure ON SCREEN. A bare `print` here goes nowhere anyone will look, which
    # is exactly how a broken script.py reads as "the engine hangs".
    message = e
    def cosmos_event_handler(sim, event):
        import sbs
        sbs.send_gui_clear(event.client_id, "")
        sbs.send_gui_text(
            event.client_id, "", "text",
            f"$text:LandingParty script.py error^{message};", 0, 0, 80, 95)
        sbs.send_gui_complete(event.client_id, "")
