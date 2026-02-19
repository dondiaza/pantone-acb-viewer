from __future__ import annotations

import math
import re
from typing import Iterable


def clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def rgb_to_hex(rgb: Iterable[int]) -> str:
    r, g, b = rgb
    return f"#{clamp8(r):02X}{clamp8(g):02X}{clamp8(b):02X}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.strip().upper()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) == 3 and all(ch in "0123456789ABCDEF" for ch in normalized):
        normalized = "".join(ch * 2 for ch in normalized)
    if len(normalized) != 6 or any(ch not in "0123456789ABCDEF" for ch in normalized):
        raise ValueError("Formato de color HEX invalido.")
    return int(normalized[0:2], 16), int(normalized[2:4], 16), int(normalized[4:6], 16)


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> tuple[int, int, int]:
    c = max(0.0, min(1.0, c))
    m = max(0.0, min(1.0, m))
    y = max(0.0, min(1.0, y))
    k = max(0.0, min(1.0, k))

    r = 255.0 * (1.0 - c) * (1.0 - k)
    g = 255.0 * (1.0 - m) * (1.0 - k)
    b = 255.0 * (1.0 - y) * (1.0 - k)
    return clamp8(r), clamp8(g), clamp8(b)


def cmyk_bytes_to_rgb(c: int, m: int, y: int, k: int) -> tuple[int, int, int]:
    c_frac = (255 - c) / 255.0
    m_frac = (255 - m) / 255.0
    y_frac = (255 - y) / 255.0
    k_frac = (255 - k) / 255.0
    return cmyk_to_rgb(c_frac, m_frac, y_frac, k_frac)


def lab_to_rgb(l_value: float, a_value: float, b_value: float) -> tuple[int, int, int]:
    x_d50, y_d50, z_d50 = lab_to_xyz_d50(l_value, a_value, b_value)
    x_d65, y_d65, z_d65 = adapt_xyz_d50_to_d65(x_d50, y_d50, z_d50)
    return xyz_to_srgb(x_d65, y_d65, z_d65)


def lab_bytes_to_rgb(l_byte: int, a_byte: int, b_byte: int) -> tuple[int, int, int]:
    l_value = (l_byte / 255.0) * 100.0
    a_value = float(a_byte) - 128.0
    b_value = float(b_byte) - 128.0
    return lab_to_rgb(l_value, a_value, b_value)


def gray_to_rgb(gray: float) -> tuple[int, int, int]:
    value = clamp8(max(0.0, min(1.0, gray)) * 255.0)
    return value, value, value


def rgb_to_cmyk(rgb: Iterable[int]) -> tuple[float, float, float, float]:
    r, g, b = [max(0.0, min(1.0, int(v) / 255.0)) for v in rgb]
    k = 1.0 - max(r, g, b)
    if k >= 1.0:
        return 0.0, 0.0, 0.0, 1.0
    denom = max(1e-9, 1.0 - k)
    c = (1.0 - r - k) / denom
    m = (1.0 - g - k) / denom
    y = (1.0 - b - k) / denom
    return (
        max(0.0, min(1.0, c)),
        max(0.0, min(1.0, m)),
        max(0.0, min(1.0, y)),
        max(0.0, min(1.0, k)),
    )


def lab_to_xyz_d50(l_value: float, a_value: float, b_value: float) -> tuple[float, float, float]:
    epsilon = 216 / 24389
    kappa = 24389 / 27

    fy = (l_value + 16.0) / 116.0
    fx = fy + (a_value / 500.0)
    fz = fy - (b_value / 200.0)

    def f_inv(t: float) -> float:
        t3 = t * t * t
        if t3 > epsilon:
            return t3
        return (116.0 * t - 16.0) / kappa

    x_ref = 0.9642
    y_ref = 1.0
    z_ref = 0.8251

    x = x_ref * f_inv(fx)
    y = y_ref * f_inv(fy)
    z = z_ref * f_inv(fz)
    return x, y, z


def adapt_xyz_d65_to_d50(x: float, y: float, z: float) -> tuple[float, float, float]:
    x_d50 = 1.0478112 * x + 0.0228866 * y + (-0.0501270) * z
    y_d50 = 0.0295424 * x + 0.9904844 * y + (-0.0170491) * z
    z_d50 = (-0.0092345) * x + 0.0150436 * y + 0.7521316 * z
    return x_d50, y_d50, z_d50


def adapt_xyz_d50_to_d65(x: float, y: float, z: float) -> tuple[float, float, float]:
    x_d65 = 0.9555766 * x + (-0.0230393) * y + 0.0631636 * z
    y_d65 = (-0.0282895) * x + 1.0099416 * y + 0.0210077 * z
    z_d65 = 0.0122982 * x + (-0.0204830) * y + 1.3299098 * z
    return x_d65, y_d65, z_d65


def xyz_to_srgb(x: float, y: float, z: float) -> tuple[int, int, int]:
    r_linear = 3.2404542 * x + (-1.5371385) * y + (-0.4985314) * z
    g_linear = (-0.9692660) * x + 1.8760108 * y + 0.0415560 * z
    b_linear = 0.0556434 * x + (-0.2040259) * y + 1.0572252 * z

    def gamma_encode(channel: float) -> float:
        if channel <= 0.0:
            return 0.0
        if channel <= 0.0031308:
            return 12.92 * channel
        return 1.055 * (channel ** (1 / 2.4)) - 0.055

    r = clamp8(gamma_encode(r_linear) * 255.0)
    g = clamp8(gamma_encode(g_linear) * 255.0)
    b = clamp8(gamma_encode(b_linear) * 255.0)
    return r, g, b


def srgb_to_xyz_d65(rgb: Iterable[int]) -> tuple[float, float, float]:
    r8, g8, b8 = [clamp8(v) for v in rgb]

    def inv_gamma(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    r = inv_gamma(r8 / 255.0)
    g = inv_gamma(g8 / 255.0)
    b = inv_gamma(b8 / 255.0)

    x = (0.4124564 * r) + (0.3575761 * g) + (0.1804375 * b)
    y = (0.2126729 * r) + (0.7151522 * g) + (0.0721750 * b)
    z = (0.0193339 * r) + (0.1191920 * g) + (0.9503041 * b)
    return x, y, z


def xyz_to_lab_d50(x: float, y: float, z: float) -> tuple[float, float, float]:
    return _xyz_to_lab(x, y, z, x_ref=0.9642, y_ref=1.0, z_ref=0.8251)


def xyz_to_lab_d65(x: float, y: float, z: float) -> tuple[float, float, float]:
    return _xyz_to_lab(x, y, z, x_ref=0.95047, y_ref=1.0, z_ref=1.08883)


def _xyz_to_lab(
    x: float,
    y: float,
    z: float,
    x_ref: float,
    y_ref: float,
    z_ref: float,
) -> tuple[float, float, float]:

    xr = x / x_ref
    yr = y / y_ref
    zr = z / z_ref

    epsilon = 216 / 24389
    kappa = 24389 / 27

    def f(t: float) -> float:
        if t > epsilon:
            return t ** (1.0 / 3.0)
        return ((kappa * t) + 16.0) / 116.0

    fx = f(xr)
    fy = f(yr)
    fz = f(zr)
    l_value = max(0.0, (116.0 * fy) - 16.0)
    a_value = 500.0 * (fx - fy)
    b_value = 200.0 * (fy - fz)
    return l_value, a_value, b_value


def rgb_to_lab_d65(rgb: Iterable[int]) -> tuple[float, float, float]:
    x_d65, y_d65, z_d65 = srgb_to_xyz_d65(rgb)
    return xyz_to_lab_d65(x_d65, y_d65, z_d65)


def rgb_to_lab_d50(rgb: Iterable[int]) -> tuple[float, float, float]:
    x_d65, y_d65, z_d65 = srgb_to_xyz_d65(rgb)
    x_d50, y_d50, z_d50 = adapt_xyz_d65_to_d50(x_d65, y_d65, z_d65)
    return xyz_to_lab_d50(x_d50, y_d50, z_d50)


def delta_e_ciede2000(
    lab1: tuple[float, float, float], lab2: tuple[float, float, float]
) -> float:
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c1 = math.sqrt((a1 * a1) + (b1 * b1))
    c2 = math.sqrt((a2 * a2) + (b2 * b2))
    c_mean = (c1 + c2) / 2.0
    c7 = c_mean**7
    g = 0.5 * (1.0 - math.sqrt(c7 / (c7 + (25.0**7) + 1e-12)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = math.sqrt((a1p * a1p) + (b1 * b1))
    c2p = math.sqrt((a2p * a2p) + (b2 * b2))

    def hue(ap: float, bb: float) -> float:
        if ap == 0.0 and bb == 0.0:
            return 0.0
        h = math.degrees(math.atan2(bb, ap))
        return h + 360.0 if h < 0.0 else h

    h1p = hue(a1p, b1)
    h2p = hue(a2p, b2)
    dlp = l2 - l1
    dcp = c2p - c1p
    dhp = 0.0
    if c1p * c2p != 0.0:
        if abs(h2p - h1p) <= 180.0:
            dhp = h2p - h1p
        elif h2p <= h1p:
            dhp = h2p - h1p + 360.0
        else:
            dhp = h2p - h1p - 360.0
    dhp_rad = math.radians(dhp / 2.0)
    dhp_term = 2.0 * math.sqrt(c1p * c2p) * math.sin(dhp_rad)

    lpm = (l1 + l2) / 2.0
    cpm = (c1p + c2p) / 2.0
    hpm = h1p + h2p
    if c1p * c2p != 0.0:
        if abs(h1p - h2p) > 180.0:
            hpm = (h1p + h2p + 360.0) / 2.0 if (h1p + h2p) < 360.0 else (h1p + h2p - 360.0) / 2.0
        else:
            hpm = (h1p + h2p) / 2.0

    t = (
        1.0
        - (0.17 * math.cos(math.radians(hpm - 30.0)))
        + (0.24 * math.cos(math.radians(2.0 * hpm)))
        + (0.32 * math.cos(math.radians((3.0 * hpm) + 6.0)))
        - (0.20 * math.cos(math.radians((4.0 * hpm) - 63.0)))
    )

    sl = 1.0 + ((0.015 * ((lpm - 50.0) ** 2)) / math.sqrt(20.0 + ((lpm - 50.0) ** 2)))
    sc = 1.0 + (0.045 * cpm)
    sh = 1.0 + (0.015 * cpm * t)
    dt = 30.0 * math.exp(-(((hpm - 275.0) / 25.0) ** 2))
    rc = 2.0 * math.sqrt((cpm**7) / ((cpm**7) + (25.0**7) + 1e-12))
    rt = -math.sin(math.radians(2.0 * dt)) * rc

    kl = 1.0
    kc = 1.0
    kh = 1.0
    dl = dlp / (kl * sl)
    dc = dcp / (kc * sc)
    dh = dhp_term / (kh * sh)
    return math.sqrt((dl * dl) + (dc * dc) + (dh * dh) + (rt * dc * dh))


def reliability_label(delta_e: float) -> str:
    if delta_e <= 1.0:
        return "Excelente"
    if delta_e <= 2.5:
        return "Bueno"
    return "Dudoso"


def parse_color_input(value: str) -> tuple[int, int, int]:
    text = value.strip()
    if not text:
        raise ValueError("Consulta de color vacia.")

    if text.startswith("#") or re.fullmatch(r"[0-9a-fA-F]{3,6}", text):
        return hex_to_rgb(text)

    lower = text.lower()
    if lower.startswith("rgb(") and text.endswith(")"):
        body = text[text.find("(") + 1 : -1]
        parts = [item.strip() for item in body.split(",")]
        if len(parts) != 3:
            raise ValueError("rgb() debe incluir 3 componentes.")
        return tuple(clamp8(float(item)) for item in parts)  # type: ignore[return-value]

    if lower.startswith("hsl(") and text.endswith(")"):
        body = text[text.find("(") + 1 : -1]
        parts = [item.strip().rstrip("%") for item in body.split(",")]
        if len(parts) != 3:
            raise ValueError("hsl() debe incluir 3 componentes.")
        h = float(parts[0]) % 360.0
        s = max(0.0, min(1.0, float(parts[1]) / 100.0))
        l = max(0.0, min(1.0, float(parts[2]) / 100.0))
        return hsl_to_rgb(h, s, l)

    if lower.startswith("cmyk(") and text.endswith(")"):
        body = text[text.find("(") + 1 : -1]
        parts = [item.strip().rstrip("%") for item in body.split(",")]
        if len(parts) != 4:
            raise ValueError("cmyk() debe incluir 4 componentes.")
        c = max(0.0, min(1.0, float(parts[0]) / 100.0))
        m = max(0.0, min(1.0, float(parts[1]) / 100.0))
        y = max(0.0, min(1.0, float(parts[2]) / 100.0))
        k = max(0.0, min(1.0, float(parts[3]) / 100.0))
        return cmyk_to_rgb(c, m, y, k)

    raise ValueError("Formato de color no soportado. Usa HEX, rgb(), hsl() o cmyk().")


def hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    c = (1.0 - abs((2.0 * l) - 1.0)) * s
    x = c * (1.0 - abs(((h / 60.0) % 2.0) - 1.0))
    m = l - (c / 2.0)

    rp = 0.0
    gp = 0.0
    bp = 0.0
    if 0.0 <= h < 60.0:
        rp, gp, bp = c, x, 0.0
    elif 60.0 <= h < 120.0:
        rp, gp, bp = x, c, 0.0
    elif 120.0 <= h < 180.0:
        rp, gp, bp = 0.0, c, x
    elif 180.0 <= h < 240.0:
        rp, gp, bp = 0.0, x, c
    elif 240.0 <= h < 300.0:
        rp, gp, bp = x, 0.0, c
    else:
        rp, gp, bp = c, 0.0, x

    return (
        clamp8((rp + m) * 255.0),
        clamp8((gp + m) * 255.0),
        clamp8((bp + m) * 255.0),
    )
