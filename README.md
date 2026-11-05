# LB 3D Box Creator

3D boxes for a LaunchBox library: it makes the **Box - 3D** picture of LaunchBox games from their **Box - Front** /
**Box - Spine** pictures and saves it where LaunchBox looks for it, one game at a time or a whole platform at once.
It makes **discs** (LaunchBox's *Disc* pictures) from the same covers, **cartridges** in 3D (*Cart - 3D*) from
photos of the cartridges (*Cart - Front*) or from the covers, **back covers** (*Box - Back*) for games without one,
looks for missing covers on the web
(libretro-thumbnails, Steam), can make small covers sharper with an AI upscale model, cuts a scanner's thin edges off
covers, gives games with no cover at all a generic one, shows a platform's boxes in a **gallery** to find bad ones, and
has new case templates painted by a local Stable Diffusion. One Python file (tkinter + Pillow), built into one exe
with PyInstaller.

**Download:** the Windows exe is on the [Releases](https://github.com/gregmol123/lb-3d-box-creator/releases) page
(`LB3DBoxCreator-<version>.exe`, no install; it puts its templates in a `box model` folder beside itself). Windows may
warn about an unknown publisher, as the exe is not signed. **From the source:** `pip install pillow`, then
`python lb_box3d_creator.py` (tested with Python 3.14 and Pillow 12). It only reads LaunchBox's XML files and writes
the new pictures into its `Images` folders.

| File | What it is |
|---|---|
| `lb_box3d_creator.py` | the whole program |
| `box model\` | case templates, each with its corner file `.json` (a box3d profile): `AI *.png`, painted with this program's AI window, and the 3 of [box3d](https://github.com/RtaSistemas/box3d) (`box3d-mvs/arcade/dvd.png`, MIT, see `box3d-LICENSE.txt`); also built into the exe |
| `build.bat` | builds `dist\LB3DBoxCreator-<version>.exe` (`--onefile --windowed --noupx`), copies `box model`, runs the exe's self-test |
| `tests\` | `python -m unittest discover -s tests` (engine with a made-up LaunchBox folder; generic covers; discs; cartridges; back covers; scan edges and the gallery; covers from a made-up libretro / Steam server; AI templates and upscaling with made-up Forge/A1111 and ComfyUI servers; the window tests need a desktop) |

## Using it

1. **LaunchBox folder**: found by itself (`D:\LaunchBox` first, then `X:\LaunchBox` on every drive), or **Browse…**.
   Platforms come from `Data\Platforms.xml` and `Data\Platforms\*.xml`; the picture folders from its `PlatformFolder`
   entries (so platforms that share another platform's folders work).
2. **Platform** (type part of its name to narrow the list), then a game. The list shows for each game: **Front**
   (✓ Box - Front, ≈ only Box - Front - Reconstructed / Fanart - Box - Front), **Spine** (✓ Box - Spine, F only a
   Box - Full), **3D** and **Disc** (how many Box - 3D / Disc pictures it has; on a platform with cartridge photos
   the last column is **Cart**, its Cart - 3D pictures); a click on a column's name sorts by it. **Show** narrows it to
   games without / with a Box - 3D, a Disc or a Cart - 3D, or without a front; **Search** by title. Very big platforms
   show the first 5000 rows (the buttons still work on all).
   **▦ Gallery of the games in the list…** shows the Box - 3D (or Disc, Cart - 3D, Box - Back) pictures of the games in the list side by
   side, small / medium / large, in the list's order, so bad ones stand out. A click shows the game in the main
   window, a right click marks it as bad (red frame), a double click opens the picture. **Select the marked games in
   the list** selects them in the main list: then choose *Replace* on the Save tab and make the selected games again.
   The gallery follows the list (Show, Search, a new platform) and new pictures; its thumbnails are made in the
   background and kept in the cache folder (`thumbs`, the newest 20,000), so it opens fast the next time.
3. **Box** tab: the case, chosen per platform.
   * *Box drawn in perspective* (no template): a cardboard box or a plastic keep case (rim colour; presets for
     Xbox 360, PS4, PS2, Wii, Switch…), turn, perspective, thickness (taken from the spine picture's shape when there
     is one). Fits any platform.
   * A template from `box model` (or **Load template…**, any PNG of an empty case): the cover and the spine are
     mapped onto the template's front and spine by their four corners. The shipped templates bring their corners;
     for others the corners are **found automatically** (the flat cover area of the template, the spine as the widest
     flat area left of it; a see-through cover window works too) and can be dragged with the mouse (arrow keys: 1 px,
     Shift: 10 px); corners you move are remembered per template (by its SHA-256, so a renamed copy keeps them). A
     template can bring its own corners in a file next to it:
     `<template>.json` (or `profile.json` beside a `template.png`) in box3d's format (`cover_quad` / `spine_quad` with
     `tl tr br bl`, scaled by `template_size`) or as `{"quads": {"front": [[x, y] x4], "spine": [...]}}`; those win
     over detection, and **Reset corners** goes back to them. **Save corners as a box3d profile…** writes them (with
     the spine logo slots) as a box3d `profile.json`; saved next to the template it is also read back here.
   * **Template layer** (Auto / Details / Light): *details* puts the case's own clips and plastic edges back over
     the new cover (templates with a flat cover area); *light* is box3d's way, the template screened over the cover
     so its gloss and highlights shine on it. Auto picks light for see-through templates (box3d's and the AI ones) and
     details for flat ones.
   * **Template colour (tint)**: *Multiply* scales the channels like box3d's `--rgb`; *Recolour the case* redraws a
     black or white case in a colour (e.g. one DVD case for PlayStation blue and Xbox green).
   * **Sharpen the covers**: box3d's light unsharp mask after the perspective warp (on by default).
4. **Artwork** tab (for the active side, front or spine — click it in the preview or use the buttons):
   picture source (LaunchBox / plain colour / keep the template's side / none), what becomes of the template's own
   picture under the side (keep it / erase it / paint over it, *Light on both sides*), fit (stretch / fill / fit
   whole), zoom, position, rotation,
   opacity, shadow, mirror; what to do when a game has no **Box - Spine**: cut it out of **Box - Full** (only when the
   front half of that scan matches the game's Box - Front, so another edition's scan is never used), or make one
   (the cover edge colour with the game's **Clear Logo** or title; box3d's *blurred band of the cover* — left,
   centre or right band, width, blur and darkness — with the logo; the blurred cover edge; the colour only; none).
   *This game only: Own picture…* replaces the front or spine of the current game (not saved in the settings).
   **When a game has no Box - Front at all** (applications, games that never had a box; on by default): a **generic
   cover** in one look for the whole platform — the platform's logo at the top and the game's name at the bottom, on
   silver with a diagonal mesh (or dark with a mesh, a plain colour, your own picture), with a black spine carrying the
   platform's name. The logo is LaunchBox's own platform logo (`Images\Platforms\<platform>\Clear Logo`) when there is
   one, else drawn from the platform's name in 80s striped letters ("Commodore VIC-20 [Applications]" → big "VIC",
   small "COMMODORE" and a big "20", like "LASER / COLOR COMPUTER 500"), or a picture of your choice; the big name and
   the small line can be typed. The game's name is its title (without TOSEC tags such as "(1988)(Publisher)") or its
   Clear Logo. The cover takes the shape of the template's front. Games with a Box - Front (or a Reconstructed /
   Fanart one) keep their own cover; the info line under the preview says "front: generic cover" for the others.
   **No Box - Front at all: look on the web first** (Automatic by default; libretro-thumbnails / Steam / Off): before a
   generic cover is made, the game's real cover is looked for in
   [libretro's thumbnail collection](https://thumbnails.libretro.com) (box art named after No-Intro / Redump / TOSEC
   titles, for consoles and home computers) and, for PC platforms (Windows, MS-DOS…), Steam's portrait library cover. A
   cover found is saved as the game's **Box - Front** in LaunchBox, as LaunchBox's own download would (main folder,
   `<title>-01.png`, never over a file), and is used from then on. Only the same title counts — spaces, punctuation,
   accents, "&"/"and" and "Legend of Zelda, The" may differ, nothing else, since a near title is often another game —
   with the game's region first (else the region in the platform's name, "Sony Playstation EU"), a release before a
   beta or demo, and on Steam the game itself or an edition of it ("— Remastered", "Enhanced"), never its soundtrack or
   a sequel. libretro's system is found from the platform's LaunchBox name (*Scrape As*) or from a name that starts
   with the system's model ("ZX Spectrum - Games", "Atari 2600/VCS"); the field under it shows the guess and takes any
   of libretro's systems by hand. Platforms of manuals, magazines, books, videos, catalogs… are never looked up on
   their own (their entries are named after games, but a game's box is not their cover). **🔎 Find this game's cover
   on the web** does it for the game shown. Folder lists are kept two weeks; a server that does not answer is left
   alone for two minutes, so a run without internet just makes generic covers.
   **Sharper small covers (AI)** (off by default): covers less high than a size you choose (800 px) are made bigger and
   sharper by an upscale model (ESRGAN, 4x-UltraSharp, SwinIR…) on the AI server of the AI window (Forge / SD.Next /
   A1111: their upscalers; ComfyUI: a model in `models\upscale_models`); **↻ Ask the AI server** lists its models,
   empty = a photo model is picked (never an anime one). Each cover is done once and kept in the cache folder; without
   a server or a model the cover stays as it is.
   **Cut a scanner's thin white or black edge off the pictures** (on by default): scanned covers often keep a strip of
   the scanner's white bed or black lid, which shows as a line along the box. The Box - Front, Box - Spine and Box -
   Full lose a side's strip when it is one even white or black, thin (white up to 3 % of the picture, black up to 1 %,
   or 3 % when black runs round all four sides, as on a black scanner lid) and the cover starts sharply after it.
   Thicker even bands are part of the cover's design and stay: PlayStation's black top, the N64's PAL frame, the Wii's
   white foot, SNES PAL frames (checked on 1200 covers of 12 platforms: it cut 40, almost all scanner edges, a few a
   thin black line of the cover's own). Only the picture used for the box and disc is cut, never LaunchBox's file; the
   info line says "scan edge cut". Switch it off for a platform whose covers have a thin even frame you want to keep.
5. **Text / Logo** tab: texts with `{title} {year} {platform} {developer} {publisher} {region} {genre} {series}
   {version}` filled in for each game, logos from files, the game's own **Clear Logo** or **Arcade - Marquee**
   (each falls back to the other), per side, with position, size, rotation, opacity, colours. **Spine logo slots
   (box3d)** adds the template profile's top / game / bottom slots (top and bottom from its `assets\logo_top.*`,
   `logo_bottom.*`; without a profile one game slot); the game slot shows the Marquee, else the Clear Logo. Layers
   marked *Only on made-up spines* stay off games that have a real spine picture.
6. **Disc** tab: the game's disc, from its Box - Front: the kind (*from the platform* by default: PlayStation's black
   disc printed to the hub, DVD for PS2 / Xbox / Wii, Blu-ray for PS3 / PS4 / Xbox One / Wii U, the small GameCube
   disc, the PSP's **UMD** — its white shell, round at the top, with the round label and its white middle, as on real
   UMD scans — else a CD; or a picture disc printed to the hole), which square of the cover goes on the label (top,
   middle, bottom) and zoom, the game's Clear Logo (else its Marquee) and its size, a line of text along the edge
   (`{title} · © {year} {publisher}`…; fields a game lacks are left out with their separators) at the top or bottom in
   a colour, the disc's size (1000 px; a UMD is that wide and 2 % higher). A game with no Box - Front gets a disc from
   its generic cover. **Disc** in the preview's view buttons shows it.
7. **Cart** tab: the game's cartridge in 3D (LaunchBox's *Cart - 3D*), from its **Cart - Front**, which in LaunchBox is
   a photo of the whole cartridge. The photo is the front, turned in perspective (**Turn**, **Seen from above**,
   **Perspective**), and a side wall follows the cartridge's own outline in the colour of its plastic, on the left or
   the right. Its **thickness** comes from the platform, as measured on the real cartridges (NES 17.5 % of the width,
   SNES 15 %, Mega Drive / Genesis 18 %, N64 15.5 %, Game Boy 13.5 %, GBA 14 %, Atari 2600 25 %, DS 11 %, HuCard 4 %…,
   16 % for others), or is set by hand. A photo with transparency (most of LaunchBox's) gives the cleanest outline; one
   without loses its even background only when the cartridge can be told from it (not a grey cartridge on grey), else
   it is used whole. **Cart** in the view buttons shows it.
   **Games without a Cart - Front** (many: on 11 of the author's platforms, 1714 games have a cover but no cartridge
   photo, NES Europe all of its 316) get one from their **cover**: choose one real photo of the platform's cartridge
   (**Use this game's Cart - Front**, or **Choose a picture…** — a transparent background is best), and its label is
   found by itself (shown in a blue frame; four sliders move it, **↻ Find the label** looks again). Each game without a
   Cart - Front then gets its Box - Front on that label (cut to the label's shape — a label much wider than the cover,
   like the Master System's strip, takes the cover's top with the title — or stretched), and is made in 3D like a
   photo. The label is found as the biggest patch unlike the plastic that fills most of its rectangle; it was right on
   NES, SNES, Mega Drive / Genesis, N64, Game Boy, Game Boy Color, GBA, Atari 2600, Master System and DS photos. Parts
   of the photo outside the label stay as they are (the Atari 2600's end label, text round a Genesis label): move the
   sliders to cover them. The info line says "Cart - Front: made from the cover".
8. **Back** tab: a **Box - Back** for games that have none, in the generic covers' look (their ground and colours,
   Artwork tab): the game's Clear Logo (else its title) at the top, up to four screenshots (Gameplay, else Game Title
   / Game Select; a picture LaunchBox holds twice is shown once), the game's description from LaunchBox in a panel (as
   large as fits, cut short with "…" when too long), and at the bottom the platform's logo with publisher, developer,
   year, genre, players and rating. Each part can be left out. It is shaped like the game's Box - Front (portrait or
   landscape; a wide back puts the screenshots down the left and the text on the right) and 1400 px high by default.
   A scanned Box - Back is never replaced nor added to; backs this program made (it marks its pictures as made by
   it) can be made again with *Replace*. **Back** in the view buttons shows it.
9. **Save** tab: **What to make** (Box - 3D, Disc, Cart - 3D, Box - Back, any of them), **Save this game to
   LaunchBox**, **Export this game to a file…** (the picture shown: the disc, cartridge or back in their views), or
   make them for the selected games / the games in the list
   / the whole platform (in several threads; **Stop** at any time). Before a run the program says how many games it
   will make pictures for, how many of them have no Box - Front (and where their covers will be looked for on the web,
   else a generic cover), skip and leave out; like box3d it stops by itself after 10 failures in a row or when more
   than 20 % fail (disk full, LaunchBox drive gone…).

Views: 3D, Front 2D, Spine 2D (each side flattened), Disc, Cart, Back; wheel = zoom, right button = pan, double
click = fit.
**Undo / Redo** (Ctrl+Z / Ctrl+Y) cover corners and settings. The interface is in English.

## AI templates (Stability Matrix)

**Box** tab → **✨ Make a template with AI (Stability Matrix)…** makes a new case template with the Stable Diffusion
that Stability Matrix runs on this PC. The program draws the empty case in perspective (or takes the current template),
the AI paints over that drawing as a photo (img2img, so the case stays exactly where it was drawn), and the painting is
cut out along the drawn outline. The cover and spine areas become see-through, keeping only the reflections the AI
painted on them (laid over the cover as light, like box3d's templates). Their corners are known from the drawing, so the
template is saved into `box model` with a box3d profile (`<name>.json`, which also records prompt, model and seed) and
needs no corner work.

1. **AI server**: the list holds Stability Matrix's packages that can paint for this program — the web UIs with the
   Automatic1111 API (Forge / Forge-Neo, SD.Next, Stable Diffusion WebUI; they need `--api` in their launch options,
   which yours have) and ComfyUI. Stability Matrix is found by itself (`X:\StabilityMatrix.exe` on every drive, its
   portable `Data` folder beside it) or with **Browse…**; only the packages' names, ids and launch options are read from
   its `settings.json`. **▶ Start in Stability Matrix** opens Stability Matrix and starts the chosen package (its
   `--launch-package` switch; when Stability Matrix is already open, press Launch there instead — it allows one copy
   only), then connects as soon as the server answers. **Other address** connects to any such server.
2. **Case**: a kind of case (DVD, Xbox 360, Xbox One, Blu-ray, PS3, Wii, Wii U, Switch, DS, PSP, CD jewel case, Mega
   Drive, PC big box, cartridge box, steelbook) with its real proportions, turn, thickness and colour — or **Repaint the
   current template** to restyle one you have.
3. **AI painting**: model (the one the web UI has loaded, else a photo-style SDXL one; Lightning / Turbo / Hyper / LCM
   models get 8 steps at CFG 2 by themselves), prompt and negative prompt (made for each kind of case), **How much the
   AI may change** (60 % by default: lower keeps closer to the drawing, higher adds more real case detail), steps, CFG,
   variants (1–6), seed (empty = random), painting size (1024 for SDXL).

**✨ Paint** makes the variants (a progress bar with the AI's live preview on web UIs; **■ Stop** ends it). Pick one
below the preview and look at it as **Box with this game** (the game chosen in the main window), **Template**, **AI
picture** or **Drawing for the AI** (dashed: where the covers go); **Reflections on the cover** sets how strongly the
painted reflections shine on the art. **💾 Save as template and use it** saves it and chooses it for the platform.

What it touches: only servers on this PC (`127.0.0.1`). Web UIs get `save_images: false` (nothing in their output
folder); choosing another model in this window loads it in the web UI, as choosing it on its own page does. ComfyUI gets
the drawing as `input\lb3d_guide.png` (overwritten each time) and paints into a preview, not its output folder. When a
busy web UI drops a finished reply, the program asks once more (same seed, same picture). A web UI started without
`--port` moves to the next free port when 7860 is taken; the program looks at 7861–7869 too.

## Where the boxes go

`<LaunchBox>\Images\<platform>\Box - 3D\` (or the platform's own Box - 3D folder from `Platforms.xml`), named as
LaunchBox names pictures: the title with `\ / : * ? " < > | '` turned into `_`, then `-01`, e.g.
`Tom Clancy_s Splinter Cell_ Blacklist-01.png`. By default the box goes into the same region subfolder its front
came from (or always into the main folder). When a game already has a Box - 3D: **skip** it (default), **replace**
the picture LaunchBox shows (the old file is copied to `<LaunchBox>\Backups\LB 3D Box Creator\<date time>\` first),
or **add** it as the next number (`-02`…). PNG with transparency (or JPG on a chosen colour), transparent margins cut,
height limited (1000 px by default). Files are written to `.tmp` and renamed, so a stopped run leaves no half
pictures. The program never changes LaunchBox's XML files; LaunchBox shows the new pictures after a restart (or an
image refresh).

Discs go the same way into `<LaunchBox>\Images\<platform>\Disc\` (round PNG with a see-through hole, or the UMD's
shell; not cut or height-limited), cartridges into `Cart - 3D\` (as high as a Box - 3D, transparent margins cut),
back covers into `Box - Back\`. Covers found on the web go into `Box - Front\` as above. Every picture the program
saves carries a "Software: LB 3D Box Creator" mark (PNG text, JPEG EXIF), which is how it tells its own back covers
from scans.

Pictures are taken as LaunchBox would: the main folder first, then the game's region folder, then others; a
Box - Spine only from the front's region folder (can be switched off), Box - Full checked against the front.

## Settings

`%USERPROFILE%\.lb_box3d_creator_config.json`: LaunchBox folder, settings per platform (case, sides, texts and
logos; *Use as default for new platforms*; *Save settings to a file…* / *Load settings from a file…* keep one
platform's settings in a `.lb3d.json` file), corners per template, save options, the AI window's settings (`ai`). Log:
`%USERPROFILE%\.lb_box3d_creator.log`. Cache: `%USERPROFILE%\.lb_box3d_creator_cache\` (libretro's folder lists, two
weeks; upscaled covers; the gallery's thumbnails in `thumbs`); it can be deleted at any time.

## Credits

* [box3d](https://github.com/RtaSistemas/box3d) (MIT, © 2026 box3d contributors): its three templates and their
  profiles ship in `box model` with `box3d-LICENSE.txt`; the profile format, the light layer, the blurred-band spine,
  the spine logo slots and the stop-on-failures rule follow it.
* The `AI *.png` templates were painted with this program's AI window on a local Stable Diffusion (Stability Matrix,
  ComfyUI, model juggernautXL); each one's `.json` records its prompt, model and seed.
* Covers from the web come from [libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails)
  (thumbnails.libretro.com) and Steam's store; none ship with the program. They belong to their publishers and are
  downloaded one by one into your own LaunchBox library, as LaunchBox's own image download does.

## Developer switches

`LB3DBoxCreator-<version>.exe --selftest report.txt` (made-up LaunchBox folder in TEMP, every template; exit code 0 =
pass),
`--screenshot shot.png [--platform P] [--game T] [--tab N] [--face spine] [--view front] [--template file.png]
[--lb <folder>]` (opens the window, shows the game, saves a picture of the program's window only), `--ai` (opens the AI
template window; with `--screenshot`, a picture of that window after `--ai-wait` ms, 7000 by default).

## Licence

MIT, see [LICENSE](LICENSE). The box3d templates in `box model` keep box3d's own MIT licence
([box3d-LICENSE.txt](box%20model/box3d-LICENSE.txt)).
