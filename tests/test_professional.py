"""Empresas, experiencia, validar habilidades, visitas y alertas."""

from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes.professional import (
    AccountTypeUpdate,
    EntryIn,
    JobAlertIn,
    alert_matches,
)
from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_user


# =====================================================
# SIN BASE DE DATOS
# =====================================================
def test_experiencia_actual_no_tiene_fin():
    entry = EntryIn(
        kind="experience",
        title="Desarrollador",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 6, 1),
        is_current=True,
    )
    assert entry.end_date is None


def test_fechas_al_reves_no_valen():
    with pytest.raises(ValidationError):
        EntryIn(
            kind="education",
            title="Ingeniería",
            start_date=date(2025, 1, 1),
            end_date=date(2024, 1, 1),
        )


def test_empresa_necesita_nombre():
    with pytest.raises(ValidationError):
        AccountTypeUpdate(account_type="company")
    AccountTypeUpdate(account_type="company", company_name="Tech SV")


def test_alerta_necesita_un_filtro():
    with pytest.raises(ValidationError):
        JobAlertIn()


def test_coincidencia_de_alertas():
    job = SimpleNamespace(
        type="internship",
        modality="remote",
        location="San Salvador",
        title="Pasantía Flutter",
        description="Buscamos estudiante de sistemas con Flutter y Firebase",
    )
    alert = SimpleNamespace(
        type="internship", modality=None, location="salvador", query="flutter"
    )
    assert alert_matches(alert, job)
    alert.query = "flutter python"
    assert not alert_matches(alert, job)
    alert.query = None
    alert.modality = "onsite"
    assert not alert_matches(alert, job)


# =====================================================
# CON BASE DE DATOS (TEST_DATABASE_URL)
# =====================================================
JOB = {
    "type": "internship",
    "title": "Pasantía Flutter",
    "description": "Buscamos estudiante de sistemas con Flutter.",
    "modality": "remote",
    "visibility": "public",
}


async def test_solo_empresas_publican_empleos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    denied = await client.post("/publications", headers=ana, json=JOB)
    assert denied.status_code == 403

    changed = await client.put(
        "/auth/account-type",
        headers=ana,
        json={"account_type": "company", "company_name": "Tech SV"},
    )
    assert changed.json()["account_type"] == "company"
    created = await client.post("/publications", headers=ana, json=JOB)
    assert created.status_code == 201, created.text
    assert created.json()["author"]["first_name"] == "Tech SV"
    assert created.json()["author"]["account_type"] == "company"


async def test_alerta_de_empleo_avisa(client):
    empresa = await make_user(client, "rrhh@tech.com", "Rrhh")
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    await client.put(
        "/auth/account-type",
        headers=empresa,
        json={"account_type": "company", "company_name": "Tech SV"},
    )
    await client.post(
        "/job-alerts", headers=ana, json={"query": "flutter", "type": "internship"}
    )
    await client.post("/publications", headers=empresa, json=JOB)

    notes = (await client.get("/notifications", headers=ana)).json()
    assert any(n["type"] == "job_alert" for n in notes)


async def test_experiencia_y_validaciones(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id = await me_id(client, ana)

    await client.patch("/profiles/me", headers=ana, json={"skills": ["Flutter"]})
    await client.post(
        "/profiles/me/entries",
        headers=ana,
        json={
            "kind": "education",
            "title": "Ingeniería en Sistemas",
            "organization": "UES",
        },
    )

    # Sin ser contactos no se puede validar.
    denied = await client.post(
        f"/profiles/{ana_id}/endorse", headers=luis, json={"skill": "Flutter"}
    )
    assert denied.status_code == 403

    request = await client.post(f"/contacts/requests/{ana_id}", headers=luis)
    await client.post(f"/contacts/requests/{request.json()['id']}/accept", headers=ana)
    ok = await client.post(
        f"/profiles/{ana_id}/endorse", headers=luis, json={"skill": "Flutter"}
    )
    assert ok.json() == [{"name": "Flutter", "count": 1, "endorsed_by_me": True}]

    profile = (await client.get(f"/profiles/{ana_id}", headers=luis)).json()
    assert profile["entries"][0]["title"] == "Ingeniería en Sistemas"
    assert profile["skill_details"][0]["count"] == 1

    # Luis vio el perfil de Ana.
    views = (await client.get("/profiles/me/views", headers=ana)).json()
    assert [v["name"] for v in views["visitors"]] == ["Luis Prueba"]


async def test_verificar_empresa_pide_datos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    await client.put(
        "/auth/account-type",
        headers=ana,
        json={"account_type": "company", "company_name": "Tech SV"},
    )
    response = await client.post("/companies/verification-request", headers=ana)
    assert response.status_code == 400
    assert "descripción" in response.json()["detail"]
