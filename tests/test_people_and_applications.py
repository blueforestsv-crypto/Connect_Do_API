"""Perfil de otra persona, CV real y postulaciones.

Requiere TEST_DATABASE_URL (ver conftest.py); si no está, se omite.
"""

import uuid

import pytest

from app.services.people_service import create_cv_token, decode_cv_token
from tests.test_publication_interactions import make_user

PDF = b"%PDF-1.4\n% CV de prueba\n"


# =====================================================
# SIN BASE DE DATOS
# =====================================================
def test_enlace_de_cv_firmado_ida_y_vuelta():
    owner = uuid.uuid4()
    assert decode_cv_token(create_cv_token(owner)) == owner
    assert decode_cv_token("basura") is None


# =====================================================
# AUXILIARES
# =====================================================
async def me_id(client, headers) -> str:
    response = await client.get("/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def upload_cv(client, headers, name="cv.pdf", data=PDF):
    return await client.put(
        "/profiles/me/cv",
        headers=headers,
        files={"file": (name, data, "application/pdf")},
    )


async def make_job(client, headers) -> str:
    # Solo las cuentas de empresa publican empleos.
    await client.put(
        "/auth/account-type",
        headers=headers,
        json={"account_type": "company", "company_name": "Empresa SV"},
    )
    response = await client.post(
        "/publications",
        headers=headers,
        json={
            "type": "job",
            "title": "Desarrollador Flutter junior",
            "description": "Buscamos estudiante de último año para app móvil.",
            "visibility": "public",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def empresa_y_ana(client):
    empresa = await make_user(client, "rrhh@empresa.com", "Empresa")
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    return empresa, ana


# =====================================================
# PERFIL DE OTRA PERSONA
# =====================================================
async def test_perfil_ajeno_oculta_correo_si_no_son_contactos(client, empresa_y_ana):
    empresa, ana = empresa_y_ana
    ana_id = await me_id(client, ana)

    response = await client.get(f"/profiles/{ana_id}", headers=empresa)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Ana"
    assert body["email"] is None
    assert body["contact_status"] == "none"
    assert body["is_me"] is False


async def test_mi_perfil_publico_muestra_mi_correo(client, empresa_y_ana):
    _, ana = empresa_y_ana
    ana_id = await me_id(client, ana)

    body = (await client.get(f"/profiles/{ana_id}", headers=ana)).json()

    assert body["is_me"] is True
    assert body["email"] == "ana@ues.edu.sv"


async def test_perfil_inexistente_da_404(client, empresa_y_ana):
    empresa, _ = empresa_y_ana
    response = await client.get(f"/profiles/{uuid.uuid4()}", headers=empresa)
    assert response.status_code == 404


async def test_habilidades_se_guardan_limpias(client, empresa_y_ana):
    _, ana = empresa_y_ana
    response = await client.patch(
        "/profiles/me",
        headers=ana,
        json={"skills": [" Flutter ", "Figma", "Flutter", ""]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["skills"] == ["Flutter", "Figma"]


# =====================================================
# CV
# =====================================================
async def test_subir_cv_y_abrirlo_yo_misma(client, empresa_y_ana):
    _, ana = empresa_y_ana
    ana_id = await me_id(client, ana)

    uploaded = await upload_cv(client, ana)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["cv_url"] == "cv.pdf"

    link = await client.post(f"/profiles/{ana_id}/cv-link", headers=ana)
    assert link.status_code == 200, link.text

    file = await client.get(link.json()["path"])
    assert file.status_code == 200
    assert file.content == PDF
    assert file.headers["content-type"] == "application/pdf"


async def test_cv_rechaza_formatos_raros(client, empresa_y_ana):
    _, ana = empresa_y_ana
    response = await upload_cv(client, ana, name="foto.png", data=b"png")
    assert response.status_code == 400


async def test_desconocido_no_puede_ver_el_cv(client, empresa_y_ana):
    empresa, ana = empresa_y_ana
    ana_id = await me_id(client, ana)
    await upload_cv(client, ana)

    response = await client.post(f"/profiles/{ana_id}/cv-link", headers=empresa)

    assert response.status_code == 403


# =====================================================
# POSTULACIONES
# =====================================================
async def test_ciclo_de_postulacion(client, empresa_y_ana):
    empresa, ana = empresa_y_ana
    ana_id = await me_id(client, ana)
    await client.patch("/profiles/me", headers=ana, json={"career": "Sistemas"})
    await upload_cv(client, ana)
    job_id = await make_job(client, empresa)

    applied = await client.post(
        "/applications",
        headers=ana,
        json={"publication_id": job_id, "cover_message": "Me interesa mucho."},
    )
    assert applied.status_code == 201, applied.text
    application = applied.json()
    # La foto del perfil al postularse ya incluye los datos del perfil.
    assert application["profile_snapshot"]["career"] == "Sistemas"

    # La empresa recibe aviso y ve la postulación.
    notes = (await client.get("/notifications", headers=empresa)).json()
    assert any(n["type"] == "application_new" for n in notes)
    received = (await client.get("/applications/received", headers=empresa)).json()
    assert [a["id"] for a in received] == [application["id"]]

    # Ahora la empresa sí puede abrir el CV.
    link = await client.post(f"/profiles/{ana_id}/cv-link", headers=empresa)
    assert link.status_code == 200, link.text

    # Cambia el estado → Ana recibe aviso.
    updated = await client.patch(
        f"/applications/{application['id']}",
        headers=empresa,
        json={"status": "interview"},
    )
    assert updated.status_code == 200
    ana_notes = (await client.get("/notifications", headers=ana)).json()
    assert any(n["type"] == "application_status" for n in ana_notes)

    mine = (await client.get("/applications/me", headers=ana)).json()
    assert mine[0]["status"] == "interview"


async def test_no_se_postula_dos_veces(client, empresa_y_ana):
    empresa, ana = empresa_y_ana
    job_id = await make_job(client, empresa)
    body = {"publication_id": job_id}

    await client.post("/applications", headers=ana, json=body)
    again = await client.post("/applications", headers=ana, json=body)

    assert again.status_code == 409
    assert again.json()["detail"] == "Ya te postulaste a esta oportunidad."


async def test_retirar_postulacion(client, empresa_y_ana):
    empresa, ana = empresa_y_ana
    job_id = await make_job(client, empresa)
    application_id = (
        await client.post("/applications", headers=ana, json={"publication_id": job_id})
    ).json()["id"]

    other = await client.delete(f"/applications/{application_id}", headers=empresa)
    assert other.status_code == 403

    response = await client.delete(f"/applications/{application_id}", headers=ana)
    assert response.status_code == 204
    assert (await client.get("/applications/me", headers=ana)).json() == []
