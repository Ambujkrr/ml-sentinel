def test_dashboard_and_assets_are_served(client):
    page = client.get('/dashboard')
    assert page.status_code == 200
    assert 'Model health at a glance' in page.text
    assert 'Register model' in page.text
    assert 'Run monitoring' in page.text
    assert client.get('/assets/dashboard.css').status_code == 200
    script = client.get('/assets/dashboard.js')
    assert script.status_code == 200
    assert "api('/monitoring/runs?limit=200')" in script.text


def test_dashboard_is_not_a_hardcoded_demo(client):
    page = client.get('/dashboard').text
    assert 'production_drifted.csv' not in page
    assert '<strong id="stat-runs">—</strong>' in page
