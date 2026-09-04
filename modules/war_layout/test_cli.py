import json

from .cli import main


def test_cli_fixture_outputs_global_limit(tmp_path, capsys):
    fixture = tmp_path / "posts.json"
    fixture.write_text(json.dumps([
        {"post_id": str(i), "author": "a", "text": f"https://link.clashofclans.com/{i}", "image_urls": [f"https://img/{i}.jpg"]}
        for i in range(1, 7)
    ]), encoding="utf-8")
    assert main(["--fixture", str(fixture)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["layouts"] == 5
    assert output["article"]["title"].startswith("国际服-顶尖冲杯阵型 ")
