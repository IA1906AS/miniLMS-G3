import main


def test_main_runs(monkeypatch, capsys):
    class FakeResp:
        def json(self):
            return {"info": {"version": "9.9.9"}}

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResp())
    main.main()
    assert "9.9.9" in capsys.readouterr().out
