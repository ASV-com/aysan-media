# aysan-media: werkafspraken voor agents

Deze repository is OPENBAAR. Alleen beeldmateriaal voor social media.
Nooit code van het voorraadsysteem, prijslijsten, klant- of ordergegevens, budgetten of tokens.

## Structuur
- `posts/` : een JPEG per post (of mp4 + cover-JPEG bij een reel), naam `JJJJ-MM-DD-onderwerp.jpg|mp4` (kleine letters, koppeltekens). Alleen eindbeeld, nooit ruw materiaal.
- `brand/` : logo's, profielfoto, omslagfoto. Niet overschrijven zonder opdracht van V. `brand/music/`: EIGEN composities (tools/make_music.py, eigendom Aysan, vrij te gebruiken). Muziek van derden nooit in deze repo.
- `tools/make_post.py` : maakt merk-afbeeldingen (navy/oranje) uit een JSON-spec, 4:5 post of 9:16 story.
- `tools/edit_media.py` : bewerkt ruwe video/foto (knippen, 9:16, kleur, geluid, ondertitels, logo, eindkaart, scenes, stabiliseren, ruisonderdrukking, muziek met ducking, woord-voor-woord ondertitels, inzoomen, productfoto-kaart, vervagen van gezichten/kentekens, slim 9:16-uitsnijden (OpenCV: pip install "opencv-python-headless<5"); alleen ffmpeg; transcriptie via de Action in de privé-repo ASV, nooit audio hier). `edit_media.py check <bestand>` = verplichte technische keuring van elk eindbestand voor het in `posts/` komt voor de Mediabewerker (ASV-skill `media-studio`). Bronnen lokaal, nooit in de repo.
- `tools/make_reel.py` + `reels/` : 9:16-reel (mp4, 8-14 s) uit 1-4 Shopify-foto's. Rendert via GitHub Actions (de sandbox kan cdn.shopify.com niet bereiken).

## Werkwijze afbeelding -> post
1. `python3 tools/make_post.py spec.json posts/<naam>.jpg`
2. Bekijk de JPEG zelf (Read-tool) voordat je hem gebruikt: tekst mag niet buiten beeld vallen of overlappen.
3. Commit + push naar `main`.
4. Openbare URL: `https://raw.githubusercontent.com/ASV-com/aysan-media/main/posts/<naam>.jpg`
   (controleer met curl dat die 200 geeft).
5. Plan de post in via Metricool (`createScheduledPost`, blogId 7170456).

Productfoto's van Shopify (cdn.shopify.com) zijn al openbaar en mogen direct als media in Metricool.

## Werkwijze reel (1x per week, Trial Reel)
1. Schrijf `reels/JJJJ-MM-DD-onderwerp.json`: {"images": [1-4 cdn.shopify.com-URL's], "kicker": "OUTLET" of leeg, "title": max 6 woorden, "price": exact Shopify-prijs + " excl. btw", "line": bv. "Op = op." (alleen outlet), "cta": "aysantruckparts.com"}. Alleen toegestane claims.
2. Commit + push naar `main`. De Action `render-reels` maakt `posts/<naam>.mp4` en cover `posts/<naam>.jpg`.
3. Wacht tot `https://raw.githubusercontent.com/ASV-com/aysan-media/main/posts/<naam>.mp4` 200 geeft (poll elke 30 s, max 10 min; `git pull` en bekijk de cover met de Read-tool).
4. Metricool `createScheduledPost`: providers instagram, instagramData {"type": "TRIAL_REEL"}, media [mp4-URL], videoThumbnailUrl [cover-URL], tekst + hashtags zoals een productpost. Geen mp4 binnen 10 min: sla de reel deze week over en meld het.

## Media van het team (Google Drive, map "Aysan Media")
Efe maakt de media, Aydin zet ze direct in Drive `1-ruw`. Mediabeheer (assistent van V, ASV-com/ASV skill `media-beheer`) haalt ze op verzoek van V op (Google Drive-tools); de geplande social-agent heeft GEEN Drive-toegang en leest alleen deze repo.
Mappen: `1-ruw` (nieuw, naam zonder datum), `3-gepubliceerd` (live geweest), `4-archief` (niet meer in gebruik), `brand`.
Keten: 1-ruw -> bewerkt -> `posts/JJJJ-MM-DD-onderwerp.jpg|mp4` -> social plant in en meldt GEPUBLICEERD op het teambord -> Mediabeheer zet een kopie in `3-gepubliceerd` -> ongebruikt/oud naar `4-archief`. Nooit definitief verwijderen. In `posts/` alleen eindbeeld, nooit ruw materiaal.
Niet gebruiken en eerst V vragen: herkenbare personen (ook tevreden klanten: schriftelijke toestemming, zet geen bestand met personen in de openbare repo voor V akkoord geeft), kentekens, klantgegevens, prijslijsten of documenten in beeld.
