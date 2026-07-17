from flask import Flask, render_template, request, redirect, session, send_file
import qrcode
import os
import pandas as pd
import uuid
import requests
import io
from supabase import create_client


app = Flask(__name__)
app.secret_key = "elohim2026"

# =========================
# SUPABASE (RENDER SAFE)
# =========================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Faltan variables SUPABASE_URL o SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


def safe_list(r):
    try:
        data = r.json()
        return data if isinstance(data, list) else []
    except:
        return []
    

    
def generar_qr(cliente_id, base_url):

    url = f"{base_url}/tarjeta/{cliente_id}"

    print("GENERANDO QR:", url)

    img = qrcode.make(url)

    archivo = io.BytesIO()
    img.save(archivo, format="PNG")
    archivo.seek(0)

    nombre_archivo = f"{cliente_id}.png"

    # Elimina el archivo si ya existe (opcional)
    try:
        supabase.storage.from_("qr-codigos").remove([nombre_archivo])
    except:
        pass

    # Subir el QR al bucket
    supabase.storage.from_("qr-codigos").upload(
        path=nombre_archivo,
        file=archivo.getvalue(),
        file_options={
            "content-type": "image/png",
            "upsert": "True"
        }
    )

    qr = supabase.storage.from_("qr-codigos").get_public_url(nombre_archivo)

    if isinstance(qr, dict):
        qr_url = qr["publicUrl"]
    else:
        qr_url = qr

    print("QR SUBIDO:", qr_url)

    return qr_url


@app.route("/")
def home():
    return render_template("registro.html")


@app.route("/registrar", methods=["POST"])
def registrar():

    nombre = request.form["nombre"]
    apellido = request.form["apellido"]
    sucursal = request.form["sucursal"]
    telefono = request.form["telefono"].strip().replace(" ", "")

    if not telefono.isdigit() or len(telefono) != 10:
        return "❌ Número inválido"

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=id&telefono=eq.{telefono}",
        headers=HEADERS
    )

    existe = safe_list(r)

    if existe:
        return redirect(f"/tarjeta/{existe[0]['id']}")

    cliente_uuid = str(uuid.uuid4())

    create = requests.post(
        f"{SUPABASE_URL}/rest/v1/clientes",
        headers=HEADERS,
        json={
            "nombre": nombre,
            "apellido": apellido,
            "sucursal": sucursal,
            "telefono": telefono,
            "uuid": cliente_uuid,
            "sellos": 0,
            "completadas": 0
        }
    )

    if create.status_code not in [200, 201]:
        return f"❌ Error creando cliente: {create.text}"

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=id&telefono=eq.{telefono}",
        headers=HEADERS
    )

    data = safe_list(r)

    if not data:
        return "❌ Cliente creado pero no encontrado"

    cliente_id = data[0]["id"]

    try:
        qr_url = generar_qr(
            cliente_id,
            request.url_root.rstrip("/")
        )

        update = requests.patch(
            f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{cliente_id}",
            headers=HEADERS,
            json={
                "qr_url": qr_url
            }
        )

        print("PATCH:", update.status_code)
        print(update.text)

    except Exception as e:
        print("ERROR AL CREAR QR:", e)

    return redirect(f"/tarjeta/{cliente_id}")

@app.route("/tarjeta/<int:id>")
def tarjeta(id):

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=*&id=eq.{id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if not data:
        return "Cliente no encontrado"

    return render_template(
        "tarjeta.html",
        cliente=data[0]
    )


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        if request.form["usuario"] == "adminelohim" and request.form["password"] == "123456lssattes!":
            session["admin"] = True
            return redirect("/admin")

        return "Credenciales incorrectas"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/admin")
def admin():

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=*",
        headers=HEADERS
    )

    return render_template("admin.html", clientes=safe_list(r))


@app.route("/buscar")
def buscar():

    if not session.get("admin"):
        return redirect("/login")

    telefono = request.args.get("telefono", "").strip()

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=*&telefono=eq.{telefono}",
        headers=HEADERS
    )

    return render_template(
        "admin.html",
        clientes=safe_list(r)
    )


# =========================
# QR API
# =========================
@app.route("/api/buscar_cliente", methods=["POST"])
def buscar_cliente():

    data = request.get_json(silent=True) or {}
    cliente_id = data.get("id")

    if not cliente_id:
        return {"error": "ID vacío"}, 400

    try:
        cliente_id = int(cliente_id)
    except:
        return {"error": "ID inválido"}, 400

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=nombre,apellido,sucursal,sellos&id=eq.{cliente_id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if not data:
        return {"error": "Cliente no encontrado"}, 404

    return data[0]


@app.route("/api/agregar_sello", methods=["POST"])
def agregar_sello():

    data = request.get_json(silent=True) or {}
    cliente_id = data.get("id")

    if not cliente_id:
        return {"error": "ID vacío"}, 400

    try:
        cliente_id = int(cliente_id)
    except:
        return {"error": "ID inválido"}, 400

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=sellos&id=eq.{cliente_id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if not data:
        return {"error": "Cliente no existe"}, 404

    sellos = data[0].get("sellos", 0)

    if sellos < 10:
        sellos += 1

    requests.patch(
        f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{cliente_id}",
        headers=HEADERS,
        json={"sellos": sellos}
    )

    return {
        "mensaje": "Sello agregado",
        "sellos": sellos
    }

@app.route("/api/quitar_sello", methods=["POST"])
def quitar_sello():

    data = request.get_json(silent=True) or {}
    cliente_id = data.get("id")

    if not cliente_id:
        return {"error": "ID vacío"}, 400

    try:
        cliente_id = int(cliente_id)
    except:
        return {"error": "ID inválido"}, 400

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=nombre,apellido,sucursal,sellos&id=eq.{cliente_id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if not data:
        return {"error": "Cliente no existe"}, 404

    cliente = data[0]
    sellos = cliente.get("sellos", 0)

    if sellos > 0:
        sellos -= 1

        requests.patch(
            f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{cliente_id}",
            headers=HEADERS,
            json={"sellos": sellos}
        )

    return {
        "mensaje": "Sello eliminado",
        "nombre": cliente["nombre"],
        "apellido": cliente["apellido"],
        "sucursal": cliente["sucursal"],
        "sellos": sellos
    }


# =========================
# RESTO
# =========================
@app.route("/agregar/<int:id>")
def agregar(id):

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=sellos&id=eq.{id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if data:
        sellos = data[0].get("sellos", 0)

        if sellos < 10:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{id}",
                headers=HEADERS,
                json={"sellos": sellos + 1}
            )

    return redirect("/admin")

@app.route("/quitar/<int:id>")
def quitar(id):

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=sellos&id=eq.{id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if data:
        sellos = data[0].get("sellos", 0)

        if sellos > 0:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{id}",
                headers=HEADERS,
                json={"sellos": sellos - 1}
            )

    return redirect("/admin")


@app.route("/reiniciar/<int:id>")
def reiniciar(id):

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=sellos,completadas&id=eq.{id}",
        headers=HEADERS
    )

    data = safe_list(r)

    if data:
        cliente = data[0]

        sellos = cliente.get("sellos", 0)
        completadas = cliente.get("completadas", 0)

        if sellos == 10:
            completadas += 1

        requests.patch(
            f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{id}",
            headers=HEADERS,
            json={"sellos": 0, "completadas": completadas}
        )

    return redirect("/admin")


@app.route("/eliminar/<int:id>")
def eliminar(id):

    if not session.get("admin"):
        return redirect("/login")
    
    r = requests.get(
    f"{SUPABASE_URL}/rest/v1/clientes?select=qr_url&id=eq.{id}",
    headers=HEADERS
)

    data = safe_list(r)

    if data:
        try:
            supabase.storage.from_("qr-codigos").remove(
                [f"{id}.png"]
            )
        except Exception as e:
            print(e)

    requests.delete(
        f"{SUPABASE_URL}/rest/v1/clientes?id=eq.{id}",
        headers=HEADERS
    )

    return redirect("/admin")


@app.route("/estadisticas")
def estadisticas():

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=sellos,completadas",
        headers=HEADERS
    )

    data = safe_list(r)

    return render_template(
        "estadisticas.html",
        clientes=len(data),
        completadas=sum(x.get("completadas", 0) for x in data),
        sellos=sum(x.get("sellos", 0) for x in data)
    )


# =========================
# EXCEL DOWNLOAD (AGREGADO)
# =========================
@app.route("/excel/download")
def excel_download():

    if not session.get("admin"):
        return redirect("/login")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/clientes?select=*",
        headers=HEADERS
    )

    df = pd.DataFrame(safe_list(r))

    archivo = "clientes.xlsx"
    df.to_excel(archivo, index=False)

    return send_file(archivo, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)