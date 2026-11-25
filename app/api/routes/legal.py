"""Páginas públicas que pide Google para publicar el inicio de sesión:
página principal, política de privacidad y condiciones de uso."""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import settings

router = APIRouter(tags=["Legal"], include_in_schema=False)

UPDATED = "25 de noviembre de 2026"


def _contact() -> str:
    email = settings.support_email.strip()
    if not email:
        return "a través de la opción de soporte dentro de la app"
    safe = escape(email)
    return f'escribiendo a <a href="mailto:{safe}">{safe}</a>'


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Connect Do</title>
<style>
  :root {{ --blue:#2563eb; --green:#16a34a; --text:#0f172a; --muted:#475569;
           --bg:#f8fafc; --card:#ffffff; --border:#e2e8f0; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --text:#e2e8f0; --muted:#94a3b8; --bg:#0b1120; --card:#111827;
             --border:#1f2937; }}
  }}
  body {{ margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
          background:var(--bg); color:var(--text); line-height:1.6; }}
  main {{ max-width:760px; margin:0 auto; padding:32px 16px 64px; }}
  .card {{ background:var(--card); border:1px solid var(--border);
           border-radius:20px; padding:28px 24px; }}
  h1 {{ margin:0 0 4px; font-size:28px; }}
  h2 {{ margin-top:28px; font-size:19px; }}
  .muted {{ color:var(--muted); font-size:14px; }}
  a {{ color:var(--blue); }}
  nav {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;
         font-weight:600; }}
  .brand {{ font-weight:800; font-size:20px; color:var(--blue); }}
</style>
</head>
<body><main>
<nav><span class="brand">Connect Do</span>
<a href="/">Inicio</a><a href="/privacidad">Privacidad</a>
<a href="/terminos">Términos</a></nav>
<div class="card">{body}</div>
</main></body></html>"""
    )


@router.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return _page(
        "Inicio",
        """
<h1>Connect Do</h1>
<p class="muted">La red de estudiantes y empresas de El Salvador.</p>
<p>Connect Do conecta a estudiantes universitarios con compañeros, pasantías
y empleos. Crea tu perfil profesional, comparte publicaciones, conversa con
tus contactos y postúlate a oportunidades desde la app.</p>
<p><a href="/privacidad">Política de privacidad</a> ·
<a href="/terminos">Condiciones de uso</a></p>
""",
    )


@router.get("/privacidad", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    return _page(
        "Política de privacidad",
        f"""
<h1>Política de privacidad</h1>
<p class="muted">Última actualización: {UPDATED}</p>

<h2>Qué datos recopilamos</h2>
<ul>
<li><b>Cuenta:</b> nombre, apellido y correo. Si entras con Google, recibimos
de Google tu nombre, correo y foto de perfil; no recibimos tu contraseña de
Google.</li>
<li><b>Perfil:</b> lo que tú agregas: universidad, carrera, ciclo, teléfono,
descripción, habilidades, portafolio, foto y currículum (CV).</li>
<li><b>Actividad:</b> publicaciones, comentarios, me gusta, guardados,
mensajes, solicitudes de contacto y postulaciones.</li>
<li><b>Dispositivo:</b> un identificador para enviarte notificaciones push,
si las aceptas.</li>
</ul>

<h2>Para qué los usamos</h2>
<p>Solo para que la app funcione: mostrar tu perfil, tus publicaciones y tus
mensajes, enviar tus postulaciones a las empresas que elijas y avisarte de tu
actividad. No vendemos tus datos ni los usamos para publicidad.</p>

<h2>Quién puede ver tu información</h2>
<ul>
<li>Tu correo y teléfono solo los ven tus contactos.</li>
<li>Tu CV solo lo ven tus contactos y las empresas a las que te postulas.</li>
<li>Si activas el perfil privado, solo tus contactos ven tu información y
tus publicaciones.</li>
</ul>

<h2>Dónde se guardan</h2>
<p>En servidores de proveedores de nube (Render y Neon). Las notificaciones
push se envían mediante Firebase Cloud Messaging de Google. Las conexiones
usan cifrado HTTPS.</p>

<h2>Tus derechos</h2>
<p>Puedes editar tu información en cualquier momento desde tu perfil. Para
borrar tu cuenta y todos tus datos, contáctanos {_contact()}.</p>

<h2>Menores de edad</h2>
<p>Connect Do está dirigida a estudiantes universitarios y profesionales
mayores de 16 años.</p>

<h2>Cambios</h2>
<p>Si cambiamos esta política, actualizaremos la fecha de arriba y te
avisaremos en la app cuando el cambio sea importante.</p>
""",
    )


@router.get("/terminos", response_class=HTMLResponse)
async def terms() -> HTMLResponse:
    return _page(
        "Condiciones de uso",
        f"""
<h1>Condiciones de uso</h1>
<p class="muted">Última actualización: {UPDATED}</p>
<p>Al usar Connect Do aceptas estas condiciones.</p>
<ul>
<li>Usa datos reales y mantén segura tu cuenta.</li>
<li>No publiques contenido falso, ofensivo, ilegal o que no te pertenezca.</li>
<li>Las ofertas de empleo y pasantías son responsabilidad de quien las
publica. Connect Do no garantiza contrataciones.</li>
<li>Podemos ocultar contenido o suspender cuentas que incumplan estas
reglas.</li>
<li>El servicio se ofrece "tal cual" y puede cambiar o tener
interrupciones.</li>
</ul>
<p>Para dudas, contáctanos {_contact()}.</p>
""",
    )
