# aysan-media: werkafspraken voor agents

Deze repository is OPENBAAR. Alleen beeldmateriaal voor social media.
Nooit code van het voorraadsysteem, prijslijsten, klant- of ordergegevens, budgetten of tokens.

## Structuur
- `posts/` : een JPEG per post, naam `JJJJ-MM-DD-onderwerp.jpg` (kleine letters, koppeltekens)
- `brand/` : logo's, profielfoto, omslagfoto. Niet overschrijven zonder opdracht van V.
- `tools/make_post.py` : maakt merk-afbeeldingen (navy/oranje) uit een JSON-spec, 4:5 post of 9:16 story.

## Werkwijze afbeelding -> post
1. `python3 tools/make_post.py spec.json posts/<naam>.jpg`
2. Bekijk de JPEG zelf (Read-tool) voordat je hem gebruikt: tekst mag niet buiten beeld vallen of overlappen.
3. Commit + push naar `main`.
4. Openbare URL: `https://raw.githubusercontent.com/ASV-com/aysan-media/main/posts/<naam>.jpg`
   (controleer met curl dat die 200 geeft).
5. Plan de post in via Metricool (`createScheduledPost`, blogId 7170456).

Productfoto's van Shopify (cdn.shopify.com) zijn al openbaar en mogen direct als media in Metricool.
