import unittest

from server.login_broker import dispatch_event, validate_event


class BrowserInputTests(unittest.TestCase):
    def test_event_validation_and_dispatch(self):
        event = validate_event({"type": "special", "key": "Enter"})
        assert event is not None
        self.assertEqual(event["key"], "Enter")
        self.assertIsNone(validate_event({"type": "insert", "text": "x" * 1025}))

        class Cdp:
            def __init__(self):
                self.calls = []

            def send(self, method, params):
                self.calls.append((method, params))

        cdp = Cdp()
        dispatch_event(cdp, {"type": "click", "x": 10.0, "y": 20.0})
        self.assertEqual([call[1]["type"] for call in cdp.calls], ["mousePressed", "mouseReleased"])

        cdp_enter = Cdp()
        dispatch_event(cdp_enter, {"type": "special", "key": "Enter"})
        self.assertEqual(len(cdp_enter.calls), 2)
        down_call, up_call = cdp_enter.calls
        self.assertEqual(down_call[1]["type"], "keyDown")
        self.assertEqual(down_call[1]["text"], "\r")
        self.assertEqual(down_call[1]["unmodifiedText"], "\r")
        self.assertEqual(down_call[1]["windowsVirtualKeyCode"], 13)
        self.assertEqual(up_call[1]["type"], "keyUp")
        self.assertNotIn("text", up_call[1])


if __name__ == "__main__":
    unittest.main()
