#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include "esp_http_server.h"
#include "SD_MMC.h"
#include "Config_Payload.h"
#include "Module_Camera.h"
#include "Module_Storage.h"
#include "System_PayloadState.h"
static httpd_handle_t _http=nullptr;
inline esp_err_t webSendText(httpd_req_t*r,const char*type,const String&s,int code=200){httpd_resp_set_type(r,type);if(code==400)httpd_resp_set_status(r,"400 Bad Request");if(code==404)httpd_resp_set_status(r,"404 Not Found");if(code==503)httpd_resp_set_status(r,"503 Service Unavailable");return httpd_resp_send(r,s.c_str(),s.length());}
inline String webStatusJson(){String s="{";s+="\"ready\":"+String(payloadReady()?"true":"false");s+=",\"camera\":"+String(cameraModuleReady()?"true":"false");s+=",\"storage\":"+String(storageModuleReady()?"true":"false");s+=",\"wifi\":"+String(payloadWifiReady()?"true":"false");s+=",\"stream\":\""+String(payloadStreamEnabled()?"ON":"OFF")+"\"";s+=",\"image_count\":"+String(storageImageCount());s+=",\"last_image\":\""+storageLastImage()+"\"";s+=",\"last_image_size\":"+String((unsigned long)storageLastImageSize());s+="}";return s;}
inline esp_err_t hStatus(httpd_req_t*r){return webSendText(r,"application/json",webStatusJson());}
inline esp_err_t hImages(httpd_req_t*r){if(!storageModuleReady())return webSendText(r,"application/json","{\"error\":\"STORAGE_NOT_READY\"}",503);String s="[";bool first=true;File root=SD_MMC.open("/");if(root){File f=root.openNextFile();while(f){String n=f.name(),u=n;u.toUpperCase();if(!f.isDirectory()&&u.endsWith(".JPG")){if(!first)s+=",";if(!n.startsWith("/"))n="/"+n;s+="{\"name\":\""+n+"\",\"size\":"+String((unsigned long)f.size())+"}";first=false;}f=root.openNextFile();}}s+="]";return webSendText(r,"application/json",s);}
inline esp_err_t hImage(httpd_req_t*r){if(!storageModuleReady())return webSendText(r,"text/plain","STORAGE_NOT_READY",503);char q[160]={0},name[128]={0};if(httpd_req_get_url_query_str(r,q,sizeof(q))!=ESP_OK||httpd_query_key_value(q,"name",name,sizeof(name))!=ESP_OK)return webSendText(r,"text/plain","BAD_REQUEST",400);String p=name;if(!p.startsWith("/"))p="/"+p;String u=p;u.toUpperCase();if(p.indexOf("..")>=0||!u.endsWith(".JPG"))return webSendText(r,"text/plain","INVALID_IMAGE_NAME",400);File f=SD_MMC.open(p,FILE_READ);if(!f)return webSendText(r,"text/plain","IMAGE_NOT_FOUND",404);httpd_resp_set_type(r,"image/jpeg");const size_t BUF=4096;uint8_t*b=(uint8_t*)malloc(BUF);if(!b){f.close();return webSendText(r,"text/plain","OUT_OF_MEMORY",503);}esp_err_t e=ESP_OK;while(f.available()){size_t n=f.read(b,BUF);if(!n)break;e=httpd_resp_send_chunk(r,(const char*)b,n);if(e!=ESP_OK)break;}free(b);f.close();if(e!=ESP_OK)return ESP_FAIL;return httpd_resp_send_chunk(r,nullptr,0);}
// The stream runs in its own task so /image, /images and /status keep answering while streaming.
static void streamTask(void*arg){httpd_req_t*r=(httpd_req_t*)arg;httpd_resp_set_type(r,"multipart/x-mixed-replace;boundary=frame");while(payloadStreamEnabled()){camera_fb_t*fb=cameraModuleGetFrame();if(!fb){vTaskDelay(pdMS_TO_TICKS(50));continue;}char head[96];int n=snprintf(head,sizeof(head),"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",(unsigned)fb->len);esp_err_t e=httpd_resp_send_chunk(r,head,n);if(e==ESP_OK)e=httpd_resp_send_chunk(r,(const char*)fb->buf,fb->len);if(e==ESP_OK)e=httpd_resp_send_chunk(r,"\r\n",2);cameraModuleReturnFrame(fb);if(e!=ESP_OK)break;vTaskDelay(pdMS_TO_TICKS(PAYLOAD_STREAM_FRAME_MS));}httpd_resp_send_chunk(r,nullptr,0);httpd_req_async_handler_complete(r);vTaskDelete(nullptr);}
inline esp_err_t hStream(httpd_req_t*r){if(!cameraModuleReady())return webSendText(r,"text/plain","CAMERA_NOT_READY",503);if(!payloadStreamEnabled())return webSendText(r,"text/plain","STREAM_OFF",503);httpd_req_t*copy=nullptr;if(httpd_req_async_handler_begin(r,&copy)!=ESP_OK)return ESP_FAIL;if(xTaskCreatePinnedToCore(streamTask,"mjpeg",8192,copy,5,nullptr,1)!=pdPASS){httpd_req_async_handler_complete(copy);return ESP_FAIL;}return ESP_OK;}
static const char WEB_GALLERY_HTML[] PROGMEM = R"HTML(<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SunSeek Camera</title><style>
:root{--bg:#0b1420;--card:#122234;--line:#27445c;--txt:#dce7f3;--dim:#8294a8;--acc:#4fd1ff;--ok:#55e38a;--bad:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px system-ui,Segoe UI,sans-serif}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0 12px 0 0}#st{color:var(--dim);font-size:13px}
button,a.b{background:#16324a;color:var(--txt);border:1px solid #2c5272;border-radius:8px;padding:9px 14px;font-weight:700;cursor:pointer;text-decoration:none;font-size:14px}
button:hover,a.b:hover{background:#1e4363}button.p{background:#0f5c8c;border-color:var(--acc)}button.on{background:#1d4d33;border-color:var(--ok)}
main{display:grid;grid-template-columns:1fr 260px;gap:14px;padding:14px 16px}
@media(max-width:800px){main{grid-template-columns:1fr}}
.view{background:#07131f;border:1px solid var(--line);border-radius:10px;min-height:300px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.view img{max-width:100%;max-height:75vh;display:block}#empty{color:var(--dim)}
.bar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}#cap{color:var(--dim)}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:80vh;overflow:auto}
.it{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between}
.it:hover{background:#16324a}.it.sel{background:#0f5c8c}.it small{color:var(--dim)}
#msg{margin-left:auto;font-weight:700}
</style></head><body>
<header><h1>SunSeek Camera</h1><span id="st">connecting…</span>
<button class="p" onclick="shoot()">&#128247; TAKE PHOTO</button>
<button id="lv" onclick="live()">&#9654; LIVE VIEW</button>
<button onclick="load(true)">&#8635; REFRESH</button><span id="msg"></span></header>
<main><div><div class="view" id="view"><span id="empty">No photo selected</span></div>
<div class="bar"><button onclick="step(1)">&#9664; Newer</button><button onclick="step(-1)">Older &#9654;</button>
<a class="b" id="dl" download>&#11015; DOWNLOAD</a><span id="cap"></span></div></div>
<div class="list" id="list"></div></main>
<script>
let imgs=[],cur=-1,streaming=false;
const $=i=>document.getElementById(i);
function msg(t,bad){$('msg').textContent=t;$('msg').style.color=bad?'var(--bad)':'var(--ok)';}
async function status(){try{const s=await (await fetch('/status',{cache:'no-store'})).json();
const ok=v=>v?'<b style="color:var(--ok)">OK</b>':'<b style="color:var(--bad)">ERR</b>';$('st').innerHTML='Camera '+ok(s.camera)+' · SD '+ok(s.storage)+' · Stream '+s.stream+' · '+s.image_count+' photos';}catch(e){$('st').textContent='camera not reachable';}}
async function load(selectNewest){try{const r=await fetch('/images',{cache:'no-store'});const t=await r.text();
let a;try{a=JSON.parse(t)}catch(e){msg(t,true);return}
if(!Array.isArray(a)){msg(a.error||'SD card not ready',true);return}
a.sort((x,y)=>y.name.localeCompare(x.name));const before=imgs.length?imgs[0].name:null;imgs=a;
$('list').innerHTML=a.map((f,i)=>`<div class="it" onclick="show(${i})"><span>${f.name.replace('/','')}</span><small>${(f.size/1024).toFixed(0)} KB</small></div>`).join('')||'<div class="it"><small>No photos yet</small></div>';
if(a.length&&(selectNewest||cur<0||a[0].name!==before))show(0);else mark();}catch(e){msg('Cannot reach camera',true)}}
function mark(){[...document.querySelectorAll('.it')].forEach((d,i)=>d.classList.toggle('sel',i===cur&&!streaming));}
function show(i){if(i<0||i>=imgs.length)return;if(streaming)live();cur=i;const f=imgs[i];const u='/image?name='+encodeURI(f.name);  /* camera does not URL-decode, keep '/' literal */
$('view').innerHTML='<img src="'+u+'" onerror="msg(\'Could not load '+f.name+'\',true)">';$('dl').href=u;$('dl').setAttribute('download',f.name.replace('/',''));
$('cap').textContent=f.name.replace('/','')+' · '+(f.size/1024).toFixed(0)+' KB';mark();}
function step(d){show(Math.max(0,Math.min(imgs.length-1,cur-d)))}
function live(){streaming=!streaming;const b=$('lv');if(streaming){$('view').innerHTML='<img src="/stream?t='+Date.now()+'" onerror="msg(\'Live view off — STREAM_OFF?\',true)">';b.textContent='■ STOP LIVE';b.classList.add('on');$('cap').textContent='LIVE';}
else{$('view').innerHTML='<span id="empty">Live view stopped</span>';b.textContent='▶ LIVE VIEW';b.classList.remove('on');$('cap').textContent='';}mark();}
async function shoot(){msg('Taking photo…');try{const r=await fetch('/capture',{cache:'no-store'});const t=await r.text();
if(r.ok){msg('Saved '+t.split(',')[0]);await load(true);}else msg(t,true);}catch(e){msg('Capture failed',true)}}
load(true);status();setInterval(status,3000);setInterval(()=>{if(!streaming)load(false)},5000);
</script></body></html>)HTML";
inline esp_err_t hRoot(httpd_req_t*r){httpd_resp_set_type(r,"text/html");return httpd_resp_send(r,WEB_GALLERY_HTML,HTTPD_RESP_USE_STRLEN);}
// Take a photo over Wi-Fi (same as the CAPTURE command).
inline esp_err_t hCapture(httpd_req_t*r){String f;size_t z=0;if(!storageCapture(f,z))return webSendText(r,"text/plain",!storageModuleReady()?"CAPTURE_FAILED: SD card not ready":!cameraModuleReady()?"CAPTURE_FAILED: camera not ready":"CAPTURE_FAILED: write failed",503);return webSendText(r,"text/plain",f+","+String((unsigned long)z));}
inline void payloadWebBegin(){
#if PAYLOAD_WIFI_AP_MODE
 WiFi.mode(WIFI_AP);WiFi.softAP(PAYLOAD_WIFI_SSID,PAYLOAD_WIFI_PASSWORD);
#else
 WiFi.mode(WIFI_STA);WiFi.begin(PAYLOAD_STA_SSID,PAYLOAD_STA_PASSWORD);unsigned long t=millis();while(WiFi.status()!=WL_CONNECTED&&millis()-t<15000)delay(100);
#endif
 httpd_config_t c=HTTPD_DEFAULT_CONFIG();c.server_port=PAYLOAD_HTTP_PORT;c.stack_size=12288;  /* default 4096 overflows when reading SD files */ c.max_uri_handlers=8;if(httpd_start(&_http,&c)==ESP_OK){httpd_uri_t a={.uri="/status",.method=HTTP_GET,.handler=hStatus,.user_ctx=nullptr};httpd_register_uri_handler(_http,&a);httpd_uri_t b={.uri="/images",.method=HTTP_GET,.handler=hImages,.user_ctx=nullptr};httpd_register_uri_handler(_http,&b);httpd_uri_t d={.uri="/image",.method=HTTP_GET,.handler=hImage,.user_ctx=nullptr};httpd_register_uri_handler(_http,&d);httpd_uri_t cap={.uri="/capture",.method=HTTP_GET,.handler=hCapture,.user_ctx=nullptr};httpd_register_uri_handler(_http,&cap);httpd_uri_t e={.uri="/stream",.method=HTTP_GET,.handler=hStream,.user_ctx=nullptr};httpd_register_uri_handler(_http,&e);httpd_uri_t f={.uri="/",.method=HTTP_GET,.handler=hRoot,.user_ctx=nullptr};httpd_register_uri_handler(_http,&f);}}
