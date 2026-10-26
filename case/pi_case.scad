// =====================================================================
// "Brotkasten" case for the C64-Jukebox: Raspberry Pi 3B, with a little "1702" monitor on top that holds a
// 2.8" ILI9341 touch display (SPI, 86 x 50 mm board, MSP2807 type).
// A small wedge like the C64, engraved keyboard on top, USB/Ethernet on the left, power + HDMI at the back, vents
// like the original. The monitor stands on the back of the slope; its wires leave it at the back and go into the case
// through a hole in the back wall, so the monitor can also stand apart (on the table it leans back by the slope, ~9 deg).
// wires_out = "collar" gives the first design: a collar under the monitor in a hole of the hood (no wires outside).
// Gehaeuse "Brotkasten" fuer die C64-Jukebox: Raspberry Pi 3B + Mini-Monitor mit 2,8"-Touch-Display.
//
//   BASE:    floor plate with 4 standoffs for the Pi (M2.5 self-tapping, 6 mm) and a rim the hood slips over,
//            vent slots under the SoC, 4 holes for M3 screws into the hood.
//   HOOD:    walls + slanted top, printed UPSIDE DOWN (top face on the bed: the engraved keyboard comes out
//            clean, no supports). Hole in the back wall for the display wires (or for the monitor's collar).
//   MONITOR: front shell (printed face down: window and engraving clean) + rear shroud (printed back end down),
//            the shroud clicks into the shell and presses the display board against two ledges.
//
// openscad -D 'part="base"' -o pi_base.stl pi_case.scad
// part = "assembly" | "look" | "section" | "section_wires" | "parts" | "base" | "hood" | "hood_print"
//        | "monitor_front" | "monitor_back" | "monitor_front_print" | "monitor_back_print" | "test_piece" | "test_print"
// =====================================================================

part = "assembly";
wires_out = "back";                     // "back": wires out of the monitor's back and into the case's back wall
                                        // (monitor can stand apart) | "collar": through a collar on the hood

/* ---- Raspberry Pi 3B (official mechanical drawing, board 85 x 56) ---- */
pi_l = 85;  pi_w = 56;  pi_t = 1.4;
pi_holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
// ports in board coordinates: x along 85 (USB/Ethernet end = x 85), y along 56 (power/HDMI edge = y 0)
eth_y = 10.25;  eth_w = 16.0;  eth_h = 13.5;
usb_y = [29.0, 47.0];  usb_w = 15.0;  usb_h = 16.0;
pwr_x = 10.6;   hdmi_x = 32.0;
led_xy = [1.5, 8.5];                    // PWR/ACT LEDs near the SD card end
under_pi = 5.0;                         // standoff height (solder joints below the board)

/* ---- 2.8" ILI9341 touch module (MSP2807 type, board 86 x 50; MEASURE yours, sellers differ) ---- */
tft_w = 86.0;  tft_h = 50.0;  tft_t = 1.6;          // PCB
tft_glass = [69.2, 50.0];                           // LCD glass with touch panel
tft_glass_t = 4.3;                                  // glass + touch panel above the PCB
tft_glass_x0 = 9.0;                                 // glass edge from the header end of the PCB
tft_win = [64.0, 46.0];                             // window (active area 57.6 x 43.2 + some black rim)
tft_tol = 0.5;                                      // play around the PCB

/* ---- case ---- */
wall = 2.0;  top_t = 2.0;  floor_t = 2.0;
in_w = 120;                                         // inside: Pi + room for the wires (C64 proportions)
in_d = 71;                                          // deeper than the Pi: keyboard + monitor on top
front_h = 38;  back_h = 50;                         // outside heights (wedge)
pi_x0 = 1.0;                                        // board edge to the left inner wall (ports reach into the wall)
pi_y0 = in_d - pi_w - 1.0;                          // power/HDMI edge 1 mm from the back wall
fit = 0.25;                                         // base rim <-> hood
rim_h = 5;  rim_t = 1.6;
screw_d = 2.6;  boss_d = 7;                         // M3 self-tapping into the hood

out_w = in_w + 2 * wall;  out_d = in_d + 2 * wall;
$fn = 40;
eps = 0.01;

// height of the top face (outside) at depth y (0 = front outer face)
function top_at(y) = front_h + (back_h - front_h) * y / out_d;
slope = atan((back_h - front_h) / out_d);

// ---------------------------------------------------------------- the Pi, rotated 180 deg:
// USB/Ethernet end -> LEFT wall, power/HDMI edge -> BACK wall, GPIO header -> front
function pi_pos(p) = [wall + pi_x0 + pi_l - p[0], wall + pi_y0 + pi_w - p[1]];
z_pcb_bot = floor_t + under_pi;
z_pcb_top = z_pcb_bot + pi_t;

module wedge(w, d, hf, hb) {            // prism, top sloping from hf (y = 0) to hb (y = d)
    polyhedron(points = [[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, hf], [w, 0, hf], [w, d, hb], [0, d, hb]],
               faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]);
}

// ---------------------------------------------------------------- decoration on the top face
key = 5.0;  pitch = 6.0;  groove = 1.0;     // groove 0.7 was too fine for a 0.4 nozzle (see test_piece)
decor_depth = 0.8;
module keyboard_cut() {                 // engraved grooves around the keys (in the top plane, local 2D)
    rows = [[0, 16], [0.5, 16], [0.8, 15], [1.2, 14]];    // [indent in keys, number of keys]
    kb_x0 = 9;  kb_y0 = 6;
    for (r = [0 : 3]) for (k = [0 : rows[r][1] - 1])
        translate([kb_x0 + (rows[r][0] + k) * pitch, kb_y0 + (3 - r) * pitch + 7.5]) difference() {
            square([key + 2 * groove, key + 2 * groove]);
            translate([groove, groove]) square([key, key]);
        }
    translate([kb_x0 + 3.2 * pitch, kb_y0]) difference() {          // space bar
        square([8 * pitch + 2 * groove, key + 2 * groove]);
        translate([groove, groove]) square([8 * pitch - (pitch - key), key]);
    }
    for (f = [0 : 3])                                              // function keys F1..F7
        translate([kb_x0 + 16.6 * pitch, kb_y0 + f * pitch * 1.0 + 1.5]) difference() {
            square([key * 1.5 + 2 * groove, key + 2 * groove]);
            translate([groove, groove]) square([key * 1.5, key]);
        }
}
module badge_cut() {                    // rainbow stripes + name (test piece; the monitor has its own)
    for (i = [0 : 4]) translate([10 + i * 3.4, 0]) polygon([[0, 0], [2.4, 0], [6.4, 8], [4, 8]]);
    translate([36, 1.2]) text("C64 JUKEBOX", size = 5.4, font = "Liberation Sans:style=Bold");
}
module top_decor() {                    // cut into the top face: decor_depth deep, along the slope
    translate([wall, 0, front_h]) rotate([slope, 0, 0]) translate([0, 0, -decor_depth]) linear_extrude(decor_depth + 0.4) {
        keyboard_cut();                 // rainbow + name are on the monitor
    }
}

// test piece: a 2 mm slab like the hood top with keys in three groove widths, stripes and the name,
// printed the same way (engraved face on the bed). Groove width and depth are written on the back.
module key_block(g) {                  // 3 x 2 keys, every groove (also between the keys) g wide
    for (r = [0 : 1]) for (k = [0 : 2]) translate([k * (key + g), r * (key + g)]) difference() {
        square([key + 2 * g, key + 2 * g]);
        translate([g, g]) square([key, key]);
    }
}
test_w = 82;  test_d = 37;
module test_piece() {                   // modelled face up; part "test_print" turns it over
    gs = [0.7, 1.0, 1.3];
    difference() {
        linear_extrude(top_t) offset(r = 2) offset(delta = -2) square([test_w, test_d]);
        translate([0, 0, top_t - decor_depth]) linear_extrude(decor_depth + 1) {
            for (i = [0 : 2]) translate([3 + i * 26, test_d - 19]) key_block(gs[i]);
            translate([-7, 3]) badge_cut();
        }
        // labels on the back (top of the print): groove widths and the depth
        translate([0, 0, -eps]) linear_extrude(0.4) mirror([0, 1, 0]) {
            for (i = [0 : 2]) translate([3 + i * 26 + 11.5, -(test_d - 14)]) text(["0.7", "1.0", "1.3"][i], size = 4,
                halign = "center", font = "Liberation Sans:style=Bold");
            translate([test_w / 2, -9]) text(str("Tiefe ", decor_depth), size = 4, halign = "center",
                font = "Liberation Sans:style=Bold");
        }
    }
}

// ---------------------------------------------------------------- hood
corner_r = 5;  front_chamfer = 1.5;     // deeper would cut through the 2 mm wall
module outer_shape() {                  // the wedge with rounded vertical corners and a bevelled front top edge
    difference() {
        intersection() {
            wedge(out_w, out_d, front_h, back_h);
            linear_extrude(back_h + 1) offset(r = corner_r) offset(delta = -corner_r) square([out_w, out_d]);
        }
        translate([-1, 0, front_h]) rotate([45, 0, 0]) translate([0, -front_chamfer / sqrt(2), -front_chamfer / sqrt(2)])
            cube([out_w + 2, front_chamfer * sqrt(2), front_chamfer * sqrt(2)]);
    }
}
module hood() {
    difference() {
        outer_shape();
        // hollow: inside wedge, down to the floor
        translate([wall, wall, -eps]) wedge(in_w, in_d, front_h - top_t + slope_dz(wall) + eps,
                                             front_h - top_t + slope_dz(wall + in_d) + eps);
        top_decor();
        ports();
        vents_back();
        if (wires_out == "collar") monitor_hole();      // the monitor's collar + wires
        else wire_hole_back();                          // the display wires come in at the back
        // base rim goes inside: nothing to cut, the rim sits inside the walls
    }
    hood_bosses();
}
function slope_dz(y) = (back_h - front_h) * y / out_d;

module ports() {
    zt = z_pcb_top;
    // left wall: Ethernet + 2 x USB (stick out of the board by ~2 mm)
    for (p = [[eth_y, eth_w, eth_h], [usb_y[0], usb_w, usb_h], [usb_y[1], usb_w, usb_h]]) {
        c = pi_pos([pi_l, p[0]]);
        translate([-eps, c[1] - p[1] / 2 - 0.6, zt - 0.6]) cube([wall + 2 * eps, p[1] + 1.2, p[2] + 1.0]);
    }
    // back wall: micro-USB power (plug overmold ~11 x 7) and HDMI (plug ~21 x 11)
    pw = pi_pos([pwr_x, 0]);
    translate([pw[0] - 6.5, out_d - wall - eps, zt - 2.5]) cube([13, wall + 2 * eps, 8.5]);
    hd = pi_pos([hdmi_x, 0]);
    translate([hd[0] - 11.5, out_d - wall - eps, zt - 3.5]) cube([23, wall + 2 * eps, 12]);
}
// hole in the back wall for the display wires, under the monitor's own wire hole: above the Pi (its plugs and the
// audio jack reach z ~17, the Ethernet jack ends at x 22), between the HDMI cut-out and the vents; the 13 Dupont
// plugs go through it one by one
wb = [26, 20, 16, 10];                  // x, bottom z (outside), width, height
module wire_hole_back() translate([wb[0], out_d - wall - 1, wb[1]]) rotate([-90, 0, 0])
    linear_extrude(wall + 2) translate([0, -wb[3]]) offset(r = 2) offset(delta = -2) square([wb[2], wb[3]]);
module vents_back() {                   // slots in the back wall, high up (warm air), like the C64's
    for (i = [0 : 7]) translate([wall + 12 + i * 5, out_d - wall - eps, back_h - 14]) cube([2.4, wall + 2 * eps, 7]);
}
boss_xy = [[wall + boss_d / 2 + fit + rim_t, wall + boss_d / 2 + fit + rim_t],
           [out_w - wall - boss_d / 2 - fit - rim_t, wall + boss_d / 2 + fit + rim_t + 9],
           [wall + boss_d / 2 + fit + rim_t, out_d - wall - boss_d / 2 - fit - rim_t],
           [out_w - wall - boss_d / 2 - fit - rim_t, out_d - wall - boss_d / 2 - fit - rim_t]];
module hood_bosses() {                  // M3 bosses from the top down to the base rim height
    for (b = boss_xy) intersection() {
        translate([b[0], b[1], floor_t + 0.3]) difference() {
            cylinder(d = boss_d, h = back_h);
            translate([0, 0, -eps]) cylinder(d = screw_d, h = 14);
        }
        translate([0, 0, 0]) wedge(out_w, out_d, front_h - 0.5, back_h - 0.5);
    }
}

// ---------------------------------------------------------------- base
module base() {
    difference() {
        union() {
            linear_extrude(floor_t) offset(r = corner_r) offset(delta = -corner_r) square([out_w, out_d]);
            // rim inside the hood walls (the hood slips over it)
            translate([wall + fit, wall + fit, 0]) difference() {
                cube([in_w - 2 * fit, in_d - 2 * fit, floor_t + rim_h]);
                translate([rim_t, rim_t, -eps]) cube([in_w - 2 * fit - 2 * rim_t, in_d - 2 * fit - 2 * rim_t, floor_t + rim_h + 1]);
                // gaps in the rim where the ports are (left wall) and at the back connectors
                translate([-eps, pi_pos([pi_l, usb_y[1]])[1] - 10 - wall - fit, floor_t]) cube([rim_t + 2 * eps, 50, rim_h + 1]);
                translate([pi_pos([hdmi_x, 0])[0] - 30 - wall - fit, in_d - 2 * fit - rim_t - eps, floor_t]) cube([55, rim_t + 2 * eps, rim_h + 1]);
            }
            for (h = pi_holes) translate([pi_pos(h)[0], pi_pos(h)[1], 0]) cylinder(d = 6, h = floor_t + under_pi);
        }
        for (h = pi_holes) translate([pi_pos(h)[0], pi_pos(h)[1], 1.0]) cylinder(d = 2.2, h = 20);
        for (b = boss_xy) translate([b[0], b[1], -eps]) { cylinder(d = 3.4, h = 10); cylinder(d = 6.2, h = 1.6); }
        // vent slots under the SoC (centre of the board)
        c = pi_pos([29, 32]);
        for (i = [-3 : 3]) translate([c[0] - 14, c[1] + i * 4.5 - 1.2, -eps]) cube([28, 2.4, floor_t + 2 * eps]);
        // name plate on the bottom
        translate([out_w / 2, 8, -eps]) mirror([1, 0, 0]) linear_extrude(0.6)
            text("C64-Jukebox  ·  Raspberry Pi 3B", size = 4, halign = "center", font = "Liberation Sans:style=Bold");
    }
}

// ---------------------------------------------------------------- dummies for the preview
module pi_dummy() {
    color("green") translate([wall + pi_x0, wall + pi_y0, z_pcb_bot]) cube([pi_l, pi_w, pi_t]);
    color("silver") {
        for (p = [[eth_y, eth_w, eth_h], [usb_y[0], usb_w, usb_h], [usb_y[1], usb_w, usb_h]]) {
            c = pi_pos([pi_l, p[0]]);
            translate([c[0] - 2, c[1] - p[1] / 2, z_pcb_top]) cube([21, p[1], p[2]]);
        }
        h = pi_pos([32.5, 52.5]);
        color("black") translate([h[0] - 25.4, h[1] - 2.5, z_pcb_top]) cube([50.8, 5, 8.5]);
    }
}

// ---------------------------------------------------------------- mini monitor ("1702") for the 2.8" display
// Monitor coordinates: x to the right (seen from the front), y backwards, z up; z = 0 at the front bottom edge,
// the floor follows the slope of the hood (z = y * m_t), so the monitor stands upright on the slanted top.
m_wall = 2.2;  m_front = 1.6;  m_gap = 0.6;         // walls, front plate, air in front of the touch panel
m_strip = 12;                                       // "control strip" below the screen
m_iw = tft_w + 2 * tft_tol;
m_w = m_iw + 2 * m_wall;
m_h = m_strip + tft_h + 2 * tft_tol + m_wall;
m_d = 30;  m_r = 4;                                 // depth of the front shell (wires: Dupont plugs behind the board)
m_t = (back_h - front_h) / out_d;                   // slope of the hood top (dz per dy)
pcb_y = m_front + tft_glass_t + m_gap;              // front face of the display board
pcb_x = m_wall + tft_tol;  pcb_z = m_strip + tft_tol;   // lower left corner of the board (header end on the left)
glass_c = [pcb_x + tft_glass_x0 + tft_glass[0] / 2, pcb_z + tft_h / 2];
sh_d = 20;  sh_inset = [16, 14, 8];                 // rear shroud: depth, inset of its back end at sides / top / bottom
tab_l = 9;  tab_w = 8;  tab_z = 34;                 // snap tabs left and right
cab = [7, 16, 26, 11];                              // wire hole in the floor: x, y, width, depth (header end)
collar_t = 1.6;  collar_h = 1.8;                    // collar around it, sits in the hood's hole
m_pos = [out_w / 2 - m_w / 2, out_d - 2 - m_d];     // monitor's front left corner on the hood

module fx(d) multmatrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]) linear_extrude(d) children();
module fxs(d, sc) multmatrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]) linear_extrude(d, scale = sc) children();
module shear_t() multmatrix([[1, 0, 0, 0], [0, 1, 0, 0], [0, m_t, 1, 0], [0, 0, 0, 1]]) children();   // z += y * m_t
module above_floor(d, dz = 0) shear_t() translate([-1, -1, dz]) cube([m_w + 2, d + 2, 200]);

module m_outline() offset(r = m_r) offset(delta = -m_r) translate([0, -10]) square([m_w, m_h + 10]);
module m_body() intersection() { fx(m_d) m_outline(); above_floor(m_d); }

module m_window() translate([glass_c[0], 0, glass_c[1]]) {
    translate([0, -eps, 0]) fx(m_front + 2 * eps) offset(r = 3) offset(delta = -3) square(tft_win, center = true);
    translate([0, -eps, 0]) fxs(1.4, [(tft_win[0] - 0.4) / (tft_win[0] + 2.4), (tft_win[1] - 0.4) / (tft_win[1] + 2.4)])
        offset(r = 4.2) offset(delta = -4.2) square(tft_win + [2.4, 2.4], center = true);    // bevel like a CRT frame
}
module m_decor() translate([0, -eps, 0]) fx(0.6 + eps) {          // engraved into the control strip
    translate([7, 3.6]) text("C64 JUKEBOX", size = 5, font = "Liberation Sans:style=Bold");
    for (i = [0 : 4]) translate([m_w - 34 + i * 2.6, 3]) polygon([[0, 0], [1.8, 0], [4.6, 6.4], [2.8, 6.4]]);
    translate([m_w - 9, 6.2]) circle(d = 2.6);                   // "power LED"
}
module m_snap_holes() for (x = [-eps, m_w - m_wall - eps])
    translate([x, m_d - tab_l - 0.2, tab_z - 0.5]) cube([m_wall + 2 * eps, 2.2, tab_w + 1]);
module m_cable_hole(grow = 0) translate([cab[0] - grow, cab[1] - grow, -20]) cube([cab[2] + 2 * grow, cab[3] + 2 * grow, 30]);

module monitor_front() {
    difference() {
        union() {
            difference() {
                m_body();
                intersection() {                                   // hollow, open at the back
                    translate([0, m_front, 0]) fx(m_d) offset(delta = -m_wall) m_outline();
                    above_floor(m_d + 2, m_wall);
                }
            }
            intersection() {
                union() {
                    // ledges at both ends of the board: it rests there, the glass floats m_gap behind the front plate
                    translate([m_wall, m_front - eps, pcb_z - tft_tol]) cube([pcb_x + tft_glass_x0 - 0.8 - m_wall, pcb_y - m_front + eps, tft_h + 2 * tft_tol]);
                    translate([pcb_x + tft_glass_x0 + tft_glass[0] + 0.8, m_front - eps, pcb_z - tft_tol])
                        cube([m_w - m_wall - (pcb_x + tft_glass_x0 + tft_glass[0] + 0.8), pcb_y - m_front + eps, tft_h + 2 * tft_tol]);
                    // shelf the lower edge of the board stands on
                    translate([m_wall - eps, m_front - eps, -5]) cube([m_iw + 2 * eps, pcb_y + tft_t + 2 - m_front, pcb_z - tft_tol + 5]);
                }
                m_body();
            }
            if (wires_out == "collar")
                shear_t() translate([cab[0] - collar_t, cab[1] - collar_t, -collar_h]) cube([cab[2] + 2 * collar_t, cab[3] + 2 * collar_t, collar_h + m_wall]);
        }
        m_window();
        m_decor();
        m_snap_holes();
        if (wires_out == "collar") m_cable_hole();
    }
}

// rear shroud (third version, 2026-10-24): a tapered "picture tube" back. The first one held the board with four
// thin fingers and clicked in with two 1.2 mm tabs - both broke off. The second one (sleeve, plates, screw) fitted, but
// let the wires out on the wrong side, through a hole and round the bottom edge. Now: the display's header is on the
// RIGHT (seen from the front; the picture is turned by the jukebox's "Bild um 180 Grad drehen"), and the shroud has a
// notch there over its whole depth, as high as the header: the plugged wires run straight back out of it, and the
// shroud slides on from behind over them. A wall inside closes the notch towards the hollow; with strain = "ties" it
// has two pairs of slots for small cable ties (2.5 mm) that hold the bundle. Held by its tight fit plus one M2 screw
// through the LEFT slot of the shell (the right one is in the notch).
hdr_right = true;                                   // header (and wires) on the right, seen from the front
strain = "ties";                                    // "ties": cable-tie slots in the notch wall | "none"
sh_wall = 2.0;                                      // walls of the tapered back
sl_y0 = 19;  sl_t = 2.0;  sl_fit = 0.15;            // sleeve: front edge (y), wall, play in the shell
plate_t = 2.0;                                      // pressure plates
scr_d = 1.7;                                        // M2 self-tapping screw
nw_t = 2.4;                                         // wall between the notch and the hollow
tie = [2.2, 3.4];                                   // cable-tie slot (y, z): ties up to 2.5 mm wide, 1.2 mm thick
module sh_big(o = 0) offset(delta = -o) intersection() { m_outline(); translate([-1, m_d * m_t]) square([m_w + 2, 200]); }
module sh_small(o = 0) translate([sh_inset[0], m_d * m_t + sh_inset[2]]) offset(delta = -o) offset(r = 3) offset(delta = -3)
    square([m_w - 2 * sh_inset[0], m_h - sh_inset[1] - m_d * m_t - sh_inset[2]]);
module sl_2d() intersection() {
    offset(delta = -(m_wall + sl_fit)) m_outline();
    translate([-1, m_d * m_t + m_wall + sl_fit]) square([m_w + 2, 200]);
}
hdr_z = [pcb_z + tft_h / 2 - 21, pcb_z + tft_h / 2 + 21];      // the header with its plugs (z range, 14 pins = 35.6 mm)
// the column of Dupont plugs (x range): 1.3 mm from the board's end, 2.5 mm wide
hdr_x = hdr_right ? [m_w - pcb_x - 3.8, m_w - pcb_x - 1.3] : [pcb_x + 1.3, pcb_x + 3.8];
nx = hdr_right ? hdr_x[0] - 1.8 : hdr_x[1] + 1.8;               // inner edge of the notch (2 x 1.8 mm play round the plugs)
scr = [m_d - tab_l - 0.2 + 1.1, tab_z - 0.5 + (tab_w + 1) / 2]; // centre (y, z) of a slot in the shell
tie_y = [m_d + 2, m_d + 8.5];                                   // the two slots of a pair (y), behind the shell's edge
tie_z = [pcb_z + tft_h / 2 - 11, pcb_z + tft_h / 2 + 11];       // two pairs

module mirror_hdr() if (hdr_right) children(); else translate([m_w, 0, 0]) mirror([1, 0, 0]) children();

module sh_outer() {                                 // the shroud's outside: sleeve + tapered back
    translate([0, sl_y0, 0]) fx(m_d + 2.5 - sl_y0) sl_2d();
    hull() {
        translate([0, m_d, 0]) fx(eps) sh_big();
        translate([0, m_d + sh_d - eps, 0]) fx(eps) sh_small();
    }
}
module notch() mirror_hdr()                         // over the whole depth, open to the right and to the back
    translate([hdr_x[0] - 1.8, sl_y0 - 1, hdr_z[0]]) cube([m_w + 1 - (hdr_x[0] - 1.8), m_d + sh_d + 2 - sl_y0, hdr_z[1] - hdr_z[0]]);

module monitor_back() {
    fy = pcb_y + tft_t;                             // back face of the display board
    xl = m_wall + sl_fit;  xr = m_w - m_wall - sl_fit;
    xs = hdr_right ? xl : xr - 7;                   // screw boss: on the side away from the header
    difference() {
        union() {
            difference() {                          // tapered back
                hull() {
                    translate([0, m_d, 0]) fx(eps) sh_big();
                    translate([0, m_d + sh_d - eps, 0]) fx(eps) sh_small();
                }
                hull() {
                    translate([0, m_d - eps, 0]) fx(eps) sh_big(sh_wall);
                    translate([0, m_d + sh_d - sh_wall, 0]) fx(eps) sh_small(sh_wall);
                }
                for (i = [-2 : 2]) translate([m_w / 2 + i * 6 - 1, m_d + sh_d - 3, hole_z + 1.4])
                    cube([2, 4, m_h - sh_inset[1] - m_d * m_t - sh_inset[2] - 10]);
            }
            translate([0, sl_y0, 0]) fx(m_d + 2.5 - sl_y0) difference() { sl_2d(); offset(delta = -sl_t) sl_2d(); }   // sleeve
            // pressure plates along the bottom and top edge of the board, joined to the sleeve's side walls
            for (z = [pcb_z + 0.4, pcb_z + tft_h - plate_t - 0.4])
                translate([xl + 0.8, fy - 0.1, z]) cube([xr - xl - 1.6, sl_y0 + 5 - fy, plate_t]);   // (clear of the rounded corners)
            translate([xs, sl_y0, scr[1] - 4.5]) cube([7, 6, 9]);   // screw boss behind the slot of the shell
            intersection() {                        // wall between the notch and the hollow, top to bottom
                mirror_hdr() translate([hdr_x[0] - 1.8 - nw_t, m_d - 2, -20]) cube([nw_t, sh_d + 4, m_h + 40]);
                sh_outer();
            }
        }
        translate([hdr_right ? xs - 1 : xs - 2, scr[0], scr[1]]) rotate([0, 90, 0]) cylinder(d = scr_d, h = 10, $fn = 16);
        notch();
        if (strain == "ties") mirror_hdr() for (y = tie_y, z = tie_z)
            translate([hdr_x[0] - 1.8 - nw_t - 1, y - tie[0] / 2, z - tie[1] / 2]) cube([nw_t + 2, tie[0], tie[1]]);
    }
}

hole_z = m_d * m_t + sh_inset[2] + 1.6 + 2;                     // lowest vent slot: 2 mm above the inner floor of the back end

module monitor_placed() translate([m_pos[0], m_pos[1], top_at(m_pos[1])]) children();
module monitor_hole() monitor_placed() m_cable_hole(collar_t + 0.3);

module tft_dummy() monitor_placed() {
    color("#2a6a2a") translate([pcb_x, pcb_y, pcb_z]) cube([tft_w, tft_t, tft_h]);
    color("#111") translate([pcb_x + tft_glass_x0, pcb_y - tft_glass_t, pcb_z]) cube([tft_glass[0], tft_glass_t, tft_glass[1]]);
    color("#3050a0") translate([glass_c[0] - 28.8, pcb_y - tft_glass_t - 0.01, glass_c[1] - 21.6]) cube([57.6, 0.01, 43.2]);
    // header with 14 Dupont plugs pointing backwards, the wires going straight on
    color("#222") translate([hdr_x[0], pcb_y + tft_t, pcb_z + tft_h / 2 - 17.8]) cube([2.5, 2.5 + 14, 35.6]);
    color("#c33") translate([hdr_x[0] + 0.6, pcb_y + tft_t + 16.5, pcb_z + tft_h / 2 - 17.8]) cube([1.3, 30, 35.6]);
}

if (part == "base") base();
if (part == "hood") hood();
// printing: the slanted top face flat on the bed (engraving on the bed side), the open bottom up
if (part == "hood_print") translate([0, out_d / cos(slope), 0]) rotate([180, 0, 0]) rotate([-slope, 0, 0])
    translate([0, 0, -front_h]) hood();
if (part == "monitor_front") monitor_front();
if (part == "monitor_back") monitor_back();
if (part == "monitor_front_placed") monitor_placed() monitor_front();      // assembly position (STEP)
if (part == "monitor_back_placed") monitor_placed() monitor_back();
if (part == "monitor_front_print") rotate([90, 0, 0]) monitor_front();                       // front face on the bed
if (part == "monitor_back_print") translate([0, 0, m_d + sh_d]) rotate([-90, 0, 0]) monitor_back();   // back end on the bed
if (part == "test_piece") color("#cfc4a0") test_piece();
if (part == "test_print") translate([0, test_d, top_t]) rotate([180, 0, 0]) test_piece();
if (part == "assembly") {
    color("#d9cfae") base();
    color("#cfc4a0", 0.55) hood();
    color("#cfc4a0", 0.55) monitor_placed() { monitor_front(); monitor_back(); }
    pi_dummy();
    tft_dummy();
}
if (part == "look") {
    color("#d9cfae") base();
    color("#cfc4a0") hood();
    color("#cfc4a0") monitor_placed() { monitor_front(); monitor_back(); }
    tft_dummy();
}
if (part == "section") intersection() {          // cut through the middle of the screen, seen from the right
    union() { color("#d9cfae") base(); color("#cfc4a0") hood(); color("#cfc4a0") monitor_placed() { monitor_front(); monitor_back(); }
              pi_dummy(); tft_dummy(); }
    translate([-1, -1, -1]) cube([m_pos[0] + glass_c[0] + 1, 200, 200]);
}
if (part == "section_wires") intersection() {    // cut through the wire hole(s), seen from the right
    union() { color("#cfc4a0") hood(); color("#cfc4a0") monitor_placed() { monitor_front(); monitor_back(); } tft_dummy();
              if (wires_out == "back") pi_dummy(); }
    translate([-1, -1, -1]) cube([wires_out == "back" ? wb[0] + wb[2] / 2 + 1 : m_pos[0] + cab[0] + cab[2] / 2 + 1, 200, 200]);
}
if (part == "section_monitor") intersection() {  // monitor only, cut through the left end of the board + finger
    union() { color("#cfc4a0") monitor_front(); color("#e0d8b8") monitor_back(); }
    translate([-1, -1, -20]) cube([pcb_x + 3, 200, 200]);
}
if (part == "parts") {                       // all parts as printed, side by side
    color("#d9cfae") base();
    color("#cfc4a0") translate([0, out_d + 15, 0]) translate([0, out_d / cos(slope), 0]) rotate([180, 0, 0])
        rotate([-slope, 0, 0]) translate([0, 0, -front_h]) hood();
    color("#cfc4a0") translate([out_w + 15, 0, 0]) rotate([90, 0, 0]) translate([0, -0, 0]) monitor_front();
    color("#cfc4a0") translate([out_w + 15, m_h + 30, m_d + sh_d]) rotate([-90, 0, 0]) monitor_back();
    color("#cfc4a0") translate([0, -test_d - 15, 0]) translate([0, test_d, top_t]) rotate([180, 0, 0]) test_piece();
}
