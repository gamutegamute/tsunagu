#pragma once

// Integration placeholder. Replace this constant with the lightweight HTML/CSS/JS
// delivered by the frontend team. The page must POST application/x-www-form-urlencoded
// data to /send using these names:
// time, people_count, water_stock, status, request_code.
const char PORTAL_HTML[] PROGMEM = R"TSUNAGU_PORTAL(
<!doctype html>
<html lang="ja">
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>TSUNAGU</title>
  <body>
    <h1>TSUNAGU</h1>
    <p>非常用報告フォームを準備しています。</p>
    <p>避難所: {{SHELTER_CODE}}</p>
  </body>
</html>
)TSUNAGU_PORTAL";
