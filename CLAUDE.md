# aysan-media: werkafspraken voor agents

Deze repository is OPENBAAR. Alleen beeldmateriaal voor social media.
Nooit code van het voorraadsysteem, prijslijsten, klant- of ordergegevens, budgetten of tokens.

## Structuur
- `posts/` : een JPEG per post, naam `JJJJ-MM-DD-onderwerp.jpg` (kleine letters, koppeltekens)
- `brand/` : logo's, profielfoto, omslagfoto. Niet overschrijven zonder opdracht van V.
- `tools/make_post.py` : maakt merk-afbeeldingen (navy/oranje) uit een JSON-spec, 4:5 post of 9:16 story.
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
Het team (Aydin) zet ruwe foto's/video's in Drive `1-ruw`. De assistent van V haalt ze op verzoek op (Google Drive-tools: search_files, download_file_content, create_file); de geplande social-agent heeft GEEN Drive-toegang en leest alleen de repo.
- `1-ruw`: inbox van het team, naam `onderwerp-1.jpg|mp4` (geen datum nodig).
- `3-gepubliceerd`: kopie van wat live is gegaan (zet de assistent er op verzoek in; de bron blijft in `1-ruw`).
- `brand`: master-kopie van logo's en profielfoto.
Geen map `2-klaar`: de overdracht naar het social-team loopt via `posts/`.

Werkwijze (op verzoek van V: "pak ruw op"): bekijk het bestand, kies de plaatsdag uit de planning, geef het de naam `JJJJ-MM-DD-onderwerp.jpg|mp4`, bewerk in Canva of met tools/make_post.py (navy/oranje merkstijl), controleer met de Read-tool, zet ALLEEN het eindbeeld/-video in `posts/` (nooit het ruwe bestand), push naar `main`. De social-agent pakt bestanden in `posts/` met een datum in de komende 7 dagen op, schrijft de teksten en plant in.
Niet gebruiken en eerst V vragen: herkenbare personen (ook tevreden klanten: schriftelijke toestemming nodig, zet geen bestand met personen in de openbare repo voor V akkoord geeft), kentekens, klantgegevens, prijslijsten of documenten in beeld. Is een bestand onbruikbaar: laat het in `1-ruw` en meld het.
