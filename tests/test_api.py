import io

SAMPLE_COUNT = 317


def upload(client, content: bytes, name: str = "statement.csv"):
    return client.post("/statements", files={"file": (name, io.BytesIO(content), "text/csv")})


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_returns_summary(client, sample_bytes):
    response = upload(client, sample_bytes, "april_to_sept.csv")

    assert response.status_code == 201
    body = response.json()
    assert body["statement"]["filename"] == "april_to_sept.csv"
    assert body["summary"]["transactions"] == SAMPLE_COUNT
    assert body["summary"]["total_spent"] == 403495.0
    assert body["summary"]["largest_expense"]["merchant"] == "Croma"


def test_list_statements_newest_first(client, sample_bytes):
    upload(client, sample_bytes, "first.csv")
    upload(client, sample_bytes, "second.csv")

    names = [s["filename"] for s in client.get("/statements").json()]

    assert names == ["second.csv", "first.csv"]


def test_upload_validation(client):
    assert upload(client, b"data", "notes.txt").status_code == 415
    assert upload(client, b"   \n", "empty.csv").status_code == 400

    garbage = upload(client, b"hello,world\n1,2\n", "garbage.csv")
    assert garbage.status_code == 422
    assert "header" in garbage.json()["detail"]

    too_big = upload(client, b"x" * (5 * 1024 * 1024 + 1), "big.csv")
    assert too_big.status_code == 413


def test_transactions_filtering_and_paging(client, sample_bytes):
    sid = upload(client, sample_bytes).json()["statement"]["id"]
    base = f"/statements/{sid}/transactions"

    everything = client.get(base, params={"limit": 1000}).json()
    assert len(everything) == SAMPLE_COUNT
    assert everything[0]["date"] >= everything[-1]["date"]  # newest first

    transport = client.get(base, params={"category": "Transport", "limit": 1000}).json()
    assert transport and {t["category"] for t in transport} == {"Transport"}

    credits = client.get(base, params={"type": "credit", "limit": 1000}).json()
    assert {t["type"] for t in credits} == {"credit"}

    netflix = client.get(base, params={"q": "netflix"}).json()
    assert len(netflix) == 6

    page = client.get(base, params={"limit": 5, "offset": 5}).json()
    assert [t["id"] for t in page] == [t["id"] for t in everything[5:10]]

    assert client.get(base, params={"type": "bogus"}).status_code == 422
    assert client.get(base, params={"limit": 0}).status_code == 422


def test_unknown_statement_is_404(client):
    insight_paths = ("summary", "monthly", "categories", "merchants", "anomalies", "recurring")
    for path in ("transactions", *insight_paths):
        assert client.get(f"/statements/999/{path}").status_code == 404
    assert client.delete("/statements/999").status_code == 404


def test_insight_endpoints(client, sample_bytes):
    sid = upload(client, sample_bytes).json()["statement"]["id"]

    summary = client.get(f"/statements/{sid}/summary").json()
    assert summary["savings_rate_pct"] == 21.0

    monthly = client.get(f"/statements/{sid}/monthly").json()
    assert [m["month"] for m in monthly] == [f"2026-0{m}" for m in range(4, 10)]

    categories = client.get(f"/statements/{sid}/categories").json()
    assert categories[0]["category"] == "Rent & Housing"
    assert abs(sum(c["share_pct"] for c in categories) - 100) < 0.5

    merchants = client.get(f"/statements/{sid}/merchants", params={"n": 3}).json()
    assert len(merchants) == 3

    recurring = {r["merchant"] for r in client.get(f"/statements/{sid}/recurring").json()}
    assert {"Netflix", "Spotify", "Airtel", "Cult Fit"} <= recurring

    anomalies = client.get(f"/statements/{sid}/anomalies").json()
    assert {a["merchant"] for a in anomalies} == {"Croma", "Uber", "Swiggy"}
    assert all(a["reason"] for a in anomalies)


def test_anomalies_work_without_a_balance_column(client):
    rows = "\n".join(
        f"0{i}/01/2026,UPI/DR/41234567890{i}/AMAZON/okaxis/Payment,{amount},"
        for i, amount in enumerate([1000, 1100, 900, 1050, 950, 30000], 1)
    )
    content = f"Date,Narration,Debit,Credit\n{rows}\n".encode()
    sid = upload(client, content).json()["statement"]["id"]

    response = client.get(f"/statements/{sid}/anomalies")

    assert response.status_code == 200  # NaN balance must not break JSON encoding
    assert response.json()[0]["balance"] is None


def test_correct_a_category(client, sample_bytes):
    sid = upload(client, sample_bytes).json()["statement"]["id"]
    friend = client.get(f"/statements/{sid}/transactions", params={"q": "Rahul"}).json()[0]
    assert friend["category"] == "Others"

    updated = client.patch(f"/transactions/{friend['id']}", json={"category": "Gifts"})

    assert updated.status_code == 200
    assert updated.json()["category"] == "Gifts"
    categories = {c["category"] for c in client.get(f"/statements/{sid}/categories").json()}
    assert "Gifts" in categories

    assert client.patch("/transactions/999999", json={"category": "X"}).status_code == 404
    assert client.patch(f"/transactions/{friend['id']}", json={"category": ""}).status_code == 422


def test_delete_cascades_to_transactions(client, sample_bytes):
    sid = upload(client, sample_bytes).json()["statement"]["id"]
    txn_id = client.get(f"/statements/{sid}/transactions").json()[0]["id"]

    assert client.delete(f"/statements/{sid}").status_code == 204

    assert client.get(f"/statements/{sid}/summary").status_code == 404
    assert client.patch(f"/transactions/{txn_id}", json={"category": "X"}).status_code == 404
    assert client.get("/statements").json() == []
