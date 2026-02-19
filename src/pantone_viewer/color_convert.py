from __future__ import annotations

from typing import Iterable


def clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def rgb_to_hex(rgb: Iterable[int]) -> str:
    r, g, b = rgb
    return f"#{clamp8(r):02X}{clamp8(g):02X}{clamp8(b):02X}"


def cmyk_bytes_to_rgb(c: int, m: int, y: int, k: int) -> tuple[int, int, int]:
    c_frac = (255 - c) / 255.0
    m_frac = (255 - m) / 255.0
    y_frac = (255 - y) / 255.0
    k_frac = (255 - k) / 255.0

    r = 255.0 * (1.0 - c_frac) * (1.0 - k_frac)
    g = 255.0 * (1.0 - m_frac) * (1.0 - k_frac)
    b = 255.0 * (1.0 - y_frac) * (1.0 - k_frac)
    return clamp8(r), clamp8(g), clamp8(b)


def lab_bytes_to_rgb(l_byte: int, a_byte: int, b_byte: int) -> tuple[int, int, int]:
    l_value = (l_byte / 255.0) * 100.0
    a_value = float(a_byte) - 128.0
    b_value = float(b_byte) - 128.0

    x_d50, y_d50, z_d50 = lab_to_xyz_d50(l_value, a_value, b_value)
    x_d65, y_d65, z_d65 = adapt_xyz_d50_to_d65(x_d50, y_d50, z_d50)
    return xyz_to_srgb(x_d65, y_d65, z_d65)


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

    # D50 reference white, normalized to Yn=1.0
    x_ref = 0.9642
    y_ref = 1.0
    z_ref = 0.8251

    x = x_ref * f_inv(fx)
    y = y_ref * f_inv(fy)
    z = z_ref * f_inv(fz)
    return x, y, z


def adapt_xyz_d50_to_d65(x: float, y: float, z: float) -> tuple[float, float, float]:
    # Bradford adaptation matrix (D50 -> D65)
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

