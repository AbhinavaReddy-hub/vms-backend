"""QR generation. Made in memory - never written to disk."""
import base64
import io


def qr_png_bytes(data: str) -> bytes:
    import qrcode
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_url(data: str) -> str:
    return "data:image/png;base64," + base64.b64encode(qr_png_bytes(data)).decode()
