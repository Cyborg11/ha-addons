(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s);};
var pad=function(n){return String(n).padStart(2,'0');};
var DAY=864e5;
var WD=['So','Mo','Di','Mi','Do','Fr','Sa'];
var WDL=['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'];
var MON=['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
var TYPES={
  stillen:{label:'Stillen',color:'var(--c-stillen)'},
  flasche:{label:'Flasche',color:'var(--c-flasche)'},
  windel:{label:'Windel',color:'var(--c-windel)'},
  wachstum:{label:'Wachstum',color:'var(--c-gewicht)'},
  gewicht:{label:'Wachstum',color:'var(--c-gewicht)'},
  spucken:{label:'Spucken',color:'var(--c-spucken)'},
  vitd:{label:'Vitamin D',color:'var(--c-vitd)'},
  schlaf:{label:'Schlaf',color:'var(--c-nacht)'},
  beikost:{label:'Beikost',color:'var(--c-beikost)'},
  temp:{label:'Temperatur',color:'var(--c-temp)'},
  medi:{label:'Medikament',color:'var(--c-medi)'}
};
var SIDE={links:'links',rechts:'rechts',beide:'beide Seiten'};
var KIND={muttermilch:'Muttermilch',pre:'Pre-Nahrung',folge:'Folgemilch'};
var DIA={nass:'nass',stuhl:'Stuhl',beides:'nass + Stuhl'};

/* ---------- Hilfen ---------- */
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function dayKey(ts){var d=new Date(ts);return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());}
function startOfDay(ts){var d=new Date(ts);d.setHours(0,0,0,0);return d;}
function hhmm(ts){var d=new Date(ts);return pad(d.getHours())+':'+pad(d.getMinutes());}
function toLocalInput(ts){var d=new Date(ts);return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());}
function fmtNum(n){return Math.round(n).toLocaleString('de-DE');}
function fmtDec(n,d){d=d==null?1:d;return n.toLocaleString('de-DE',{minimumFractionDigits:d,maximumFractionDigits:d});}
function fmtDur(min){min=Math.round(min);if(min<1)return 'unter 1 Min';var h=Math.floor(min/60),m=min%60;if(!h)return m+' Min';return m?h+' Std '+m+' Min':h+' Std';}
function ago(ts){var m=(Date.now()-ts)/6e4;if(m<1)return 'gerade eben';return 'vor '+fmtDur(m);}
function dLabel(d){return WD[d.getDay()]+' '+d.getDate()+'. '+MON[d.getMonth()];}
function mean(a){return a.length?a.reduce(function(s,x){return s+x;},0)/a.length:null;}
function h(tag,props){
  var e=document.createElement(tag);
  if(props)for(var k in props){var v=props[k];if(v==null||v===false)continue;
    if(k==='class')e.className=v;else if(k==='text')e.textContent=v;
    else if(k.slice(0,2)==='on')e.addEventListener(k.slice(2),v);
    else if(k==='value'||k==='checked'||k==='disabled'||k==='hidden')e[k]=v;
    else e.setAttribute(k,v===true?'':v);}
  for(var i=2;i<arguments.length;i++){var c=arguments[i];if(c==null||c===false)continue;
    (Array.isArray(c)?c:[c]).forEach(function(x){if(x==null||x===false)return;e.append(x.nodeType?x:document.createTextNode(x));});}
  return e;
}

/* ---------- Zustand ---------- */
var db=null,dl=null,canWrite=true;
var events=[],growth=[],settings={};
var view='erfassen',range=7,histDays=7,armed=null;
var notices={};
var timer=null;
try{timer=JSON.parse(localStorage.getItem('trinkprotokoll-timer')||'null');}catch(e){timer=null;}
function saveTimer(){try{if(timer)localStorage.setItem('trinkprotokoll-timer',JSON.stringify(timer));else localStorage.removeItem('trinkprotokoll-timer');}catch(e){}}

function lastOf(type){for(var i=0;i<events.length;i++){var t=events[i].type;if(t===type||(type==='wachstum'&&t==='gewicht'))return events[i];}return null;}
function describe(e){
  switch(e.type){
    case 'stillen':return {t:'Stillen',d:[SIDE[e.side]||'',(+e.min||0)+' Min'].filter(Boolean).join(' · ')};
    case 'flasche':return {t:'Flasche',d:(+e.ml||0)+' ml'+(KIND[e.kind]?' · '+KIND[e.kind]:'')};
    case 'windel':return {t:'Windel',d:DIA[e.diaper]||''};
    case 'gewicht':case 'wachstum':return {t:'Wachstum',d:[+e.g>0?fmtNum(+e.g)+' g':'',+e.len>0?fmtDec(+e.len)+' cm':'',+e.head>0?'Kopf '+fmtDec(+e.head)+' cm':''].filter(Boolean).join(' · ')};
    case 'spucken':return {t:'Spucken',d:e.amount||''};
    case 'schlaf':{var sm=+e.min||0,sw=+e.wach||0,nt=e.kind==='nacht';return {t:nt?'Nachtschlaf':'Nickerchen',d:[fmtDur(nt?sm-sw:sm),'bis '+hhmm(e.ts+sm*6e4),sw>0?'wach '+fmtDur(sw)+(+e.n>0?' ('+e.n+'×)':''):''].filter(Boolean).join(' · ')};}
    case 'beikost':return {t:'Beikost',d:+e.g>0?fmtNum(+e.g)+' g':''};
    case 'temp':{var tf=tempFlag(+e.c);return {t:'Temperatur',d:[fmtC(e.c),WHERE[e.where]||'',tf].filter(Boolean).join(' · ')};}
    case 'medi':return {t:'Medikament',d:[e.name||'',e.dose||''].filter(Boolean).join(' · ')};
    case 'vitd':return {t:'Vitamin D',d:'gegeben'};
  }
  return {t:String(e.type||'Eintrag'),d:''};
}

/* ---------- Auswertung ---------- */
function buildDays(n){
  var days=[],map={},today=startOfDay(refNow());
  for(var i=n-1;i>=0;i--){
    var d=new Date(today);d.setDate(d.getDate()-i);
    var o={key:dayKey(d),date:d,isToday:i===0,stillen:0,flasche:0,ml:0,min:0,nass:0,stuhl:0,diapers:0,spucken:0,vitd:0,nap:0,night:0,naps:0,brei:0,temp:0,medi:0,feeds:[],dia:[]};
    days.push(o);map[o.key]=o;
  }
  events.forEach(function(e){
    if(e.type==='schlaf'&&e.kind==='nacht'){var wd=map[dayKey(e.ts+(+e.min||0)*6e4)];if(wd)wd.night+=Math.max(0,(+e.min||0)-(+e.wach||0));return;}
    var o=map[dayKey(e.ts)];if(!o)return;
    if(e.type==='schlaf'){o.nap+=+e.min||0;o.naps++;}
    else if(e.type==='beikost'){o.brei++;}
    else if(e.type==='temp'){o.temp++;}
    else if(e.type==='medi'){o.medi++;}
    else if(e.type==='stillen'){o.stillen++;o.min+=+e.min||0;o.feeds.push(e);}
    else if(e.type==='flasche'){o.flasche++;o.ml+=+e.ml||0;o.feeds.push(e);}
    else if(e.type==='windel'){o.diapers++;if(e.diaper==='nass')o.nass++;else o.stuhl++;o.dia.push(e);}
    else if(e.type==='spucken')o.spucken++;
    else if(e.type==='vitd')o.vitd++;
  });
  return days;
}
function gaps(list){
  var t=list.map(function(e){return e.ts;}).sort(function(a,b){return a-b;}),g=[];
  for(var i=1;i<t.length;i++){var m=(t[i]-t[i-1])/6e4;if(m<=480)g.push(m);}
  return g;
}
function ageText(){
  if(!settings.birth)return null;
  var b=new Date(settings.birth+'T00:00:00');if(isNaN(b))return null;
  var days=Math.round((startOfDay(refNow())-b)/DAY);if(days<0)return null;
  if(days<14)return 'Tag '+(days+1);
  if(days<84){var w=Math.floor(days/7),r=days%7;return w+' Wochen'+(r?', '+r+' Tage':'');}
  var ref=new Date(refNow()),mo=(ref.getFullYear()-b.getFullYear())*12+ref.getMonth()-b.getMonth();if(ref.getDate()<b.getDate())mo--;return Math.max(2,mo)+' Monate';
}

/* ---------- Meldungen, Toast, Tooltip ---------- */
function updateNotice(){
  var t=notices.nodb||notices.err||notices.ro||notices.conn||notices.stale||notices.archiv||'';
  var n=$('#notice');n.hidden=!t;n.textContent=t;
}
var toastT=null;
function toast(msg,undo){
  var t=$('#toast');t.textContent='';t.append(h('span',{text:msg}));
  if(undo)t.append(h('button',{type:'button',text:'Rückgängig',onclick:function(){t.hidden=true;undo();}}));
  t.hidden=false;clearTimeout(toastT);toastT=setTimeout(function(){t.hidden=true;},undo?7000:3500);
}
var tip=$('#tip');
function showTip(text,x,y){
  tip.textContent='';
  text.split('|').forEach(function(line,i){tip.append(h(i?'span':'strong',{text:line}));});
  tip.hidden=false;
  var r=tip.getBoundingClientRect();
  var left=Math.min(Math.max(8,x-r.width/2),window.innerWidth-r.width-8);
  var top=y-r.height-14;if(top<8)top=y+20;
  tip.style.left=left+'px';tip.style.top=top+'px';
}
function onPointer(e){
  var t=e.target&&e.target.closest?e.target.closest('[data-tip]'):null;
  if(t)showTip(t.getAttribute('data-tip'),e.clientX,e.clientY);else tip.hidden=true;
}
document.addEventListener('pointermove',function(e){if(e.pointerType==='mouse')onPointer(e);});
document.addEventListener('pointerdown',onPointer);
window.addEventListener('scroll',function(){tip.hidden=true;},{passive:true});

/* ---------- Erfassen ---------- */
var ACTIONS=['stillen','flasche','schlaf','windel','beikost','wachstum','temp','medi','spucken','vitd'];
function buildActions(){
  var host=$('#actions');host.textContent='';
  ACTIONS.forEach(function(t,i){
    var b=h('button',{type:'button',class:'act'+(i<2?' main':''),'data-t':t,disabled:!canWrite,onclick:function(){openSheet(t);}},
      h('span',{class:'bar',style:'background:'+TYPES[t].color}),
      h('span',{class:'al',text:TYPES[t].label}),
      h('span',{class:'as','data-last':t,text:'–'}));
    host.append(b);
  });
}
function renderToday(){
  var feeds=events.filter(function(e){return e.type==='stillen'||e.type==='flasche';});
  var last=feeds[0];
  $('#lastFeed').textContent=last?ago(last.ts):'Noch nichts erfasst';
  var ds=describe(last||{});
  $('#lastFeedSub').textContent=last?hhmm(last.ts)+' · '+ds.t+(ds.d?' · '+ds.d:''):'';
  var today=buildDays(1)[0];
  var g=mean(gaps(today.feeds));
  $('#gapToday').textContent=g==null?'–':fmtDur(g);
  document.querySelectorAll('[data-last]').forEach(function(el){
    var t=el.getAttribute('data-last'),e=lastOf(t);
    if(t==='vitd')el.textContent=e&&dayKey(e.ts)===dayKey(Date.now())?'heute um '+hhmm(e.ts):'heute noch nicht';
    else if(t==='temp')el.textContent=e?fmtC(e.c)+' · '+ago(e.ts):'noch nie';
    else if(t==='medi')el.textContent=e?(e.name||'')+' · '+ago(e.ts):'noch nie';
    else el.textContent=e?ago(e.ts):'noch nie';
  });
  var s=$('#today');s.textContent='';
  [[today.stillen+today.flasche,'Mahlzeiten'],[fmtNum(today.ml),'ml Flasche'],[today.min,'Min Stillen'],[today.diapers,'Windeln']].forEach(function(p){
    s.append(h('div',null,h('dd',{text:String(p[0])}),h('dt',{text:p[1]})));
  });
  $('#emptyHint').hidden=events.length>0;
  renderBanner();renderSleepBanner();
}
function renderBanner(){
  var b=$('#timerBanner');
  if(!timer){b.hidden=true;return;}
  var s=Math.max(0,Math.floor((Date.now()-timer.start)/1000));
  b.hidden=false;b.textContent='';
  b.append('Stillen läuft seit ',h('output',{text:pad(Math.floor(s/60))+':'+pad(s%60)}),' · zum Beenden tippen');
}
$('#timerBanner').addEventListener('click',function(){openSheet('stillen');});

/* ---------- Verlauf ---------- */
function renderHistory(){
  var host=$('#hist');host.textContent='';
  var whos={};events.forEach(function(x){if(x.by)whos[x.by]=1;});var multi=Object.keys(whos).length>1;
  if(!events.length){host.append(h('p',{class:'empty',text:'Noch keine Einträge. Unter „Erfassen“ legst du den ersten an.'}));$('#moreDays').hidden=true;return;}
  var groups=[],map={};
  events.forEach(function(e){var k=dayKey(e.ts),g=map[k];if(!g){g=map[k]={ts:e.ts,items:[]};groups.push(g);}g.items.push(e);});
  if(canWrite)host.append(h('p',{class:'hintl',text:'Zum Ändern einen Eintrag antippen.'}));
  groups.slice(0,histDays).forEach(function(g){
    var d=startOfDay(g.ts),diff=Math.round((startOfDay(refNow())-d)/DAY);
    var title=!anchor&&diff===0?'Heute':!anchor&&diff===1?'Gestern':WDL[d.getDay()]+', '+d.getDate()+'. '+MON[d.getMonth()];
    var f=g.items.filter(function(e){return e.type==='stillen'||e.type==='flasche';}).length;
    var ml=g.items.reduce(function(s,e){return s+(e.type==='flasche'?+e.ml||0:0);},0);
    var w=g.items.filter(function(e){return e.type==='windel';}).length;
    var sum=[f?f+' Mahlzeiten':'',ml?fmtNum(ml)+' ml':'',w?w+' Windeln':''].filter(Boolean).join(' · ');
    var ul=h('ul',{class:'rows'});
    g.items.forEach(function(e){
      var ds=describe(e);
      ul.append(h('li',{class:'row'},
        h('span',{class:'dot',style:'background:'+(TYPES[e.type]?TYPES[e.type].color:'var(--axis)')}),
        h('div',canWrite?{class:'edit',role:'button',tabindex:'0','aria-label':'Eintrag bearbeiten',onclick:function(){editEvent(e);},onkeydown:function(k){if(k.key==='Enter'||k.key===' '){k.preventDefault();editEvent(e);}}}:null,h('p',{class:'rt'},ds.t,ds.d?h('span',{class:'rd',text:' · '+ds.d}):null),(multi&&e.by)||e.note?h('p',{class:'rn',text:[multi?e.by:'',e.note].filter(Boolean).join(' · ')}):null),
        h('time',canWrite?{text:hhmm(e.ts),class:'edit',onclick:function(){editEvent(e);}}:{text:hhmm(e.ts)}),
        canWrite?h('button',{type:'button',class:'del'+(armed===e.id?' armed':''),text:armed===e.id?'Wirklich löschen':'Löschen',onclick:function(){delEvent(e.id);}}):null));
    });
    host.append(h('div',{class:'day'},h('div',{class:'day-h'},h('h3',{text:title}),h('p',{text:sum})),ul));
  });
  $('#moreDays').hidden=groups.length<=histDays;
}
function delEvent(id){
  if(armed!==id){armed=id;renderHistory();setTimeout(function(){if(armed===id){armed=null;if(view==='verlauf')renderHistory();}},4000);return;}
  armed=null;
  db.collection('events').doc(id).delete().catch(function(){toast('Löschen hat nicht geklappt.');});
}
$('#moreDays').addEventListener('click',function(){histDays+=7;renderHistory();});

/* ---------- Diagramme ---------- */
function yScale(maxV,minStep){
  var raw=Math.max(maxV,1)/4,p=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/p;
  var s=Math.max(minStep||1,(f<=1?1:f<=2?2:f<=5?5:10)*p);
  return {step:s,max:Math.max(Math.ceil(maxV/s)*s,s)};
}
function rtop(x,y,w,hh,r){r=Math.min(r,hh,w/2);return 'M'+x+','+(y+hh)+'V'+(y+r)+'Q'+x+','+y+' '+(x+r)+','+y+'H'+(x+w-r)+'Q'+(x+w)+','+y+' '+(x+w)+','+(y+r)+'V'+(y+hh)+'Z';}
function legend(id,items){
  var el=$(id);el.textContent='';
  items.forEach(function(i){el.append(h('span',{class:'lg'},h('i',{class:'sw '+(i.shape||''),style:'background:'+i.color}),i.label));});
}
function barChart(host,days,series,opt){
  var n=days.length,W=Math.max(260,host.clientWidth||320),H=opt.h||180;
  var m={l:38,r:6,t:16,b:n<=8?36:26},pw=W-m.l-m.r,ph=H-m.t-m.b;
  var totals=days.map(function(d){return series.reduce(function(s,x){return s+x.val(d);},0);});
  var ys=yScale(Math.max.apply(null,totals.concat([0])),opt.minStep);
  var y=function(v){return m.t+ph-(v/ys.max)*ph;};
  var slot=pw/n,bw=Math.min(slot*.62,34);
  var s='<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="'+esc(opt.label)+'">';
  for(var v=0;v<=ys.max+1e-9;v+=ys.step){
    var yy=y(v);
    s+='<line class="'+(v===0?'ax':'gr')+'" x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+yy+'" y2="'+yy+'"/><text x="'+(m.l-6)+'" y="'+(yy+4)+'" text-anchor="end">'+fmtNum(v)+'</text>';
  }
  days.forEach(function(d,i){
    var cx=m.l+slot*(i+.5),x=cx-bw/2,acc=0,top=-1;
    series.forEach(function(sr,k){if(sr.val(d)>0)top=k;});
    series.forEach(function(sr,k){
      var val=sr.val(d);if(val<=0)return;
      var y1=y(acc+val),y0=y(acc),hh=y0-y1;
      s+=k===top?'<path d="'+rtop(x,y1,bw,hh,4)+'" fill="'+sr.color+'" stroke="var(--surface)" stroke-width="2"/>'
        :'<rect x="'+x+'" y="'+y1+'" width="'+bw+'" height="'+hh+'" fill="'+sr.color+'" stroke="var(--surface)" stroke-width="2"/>';
      acc+=val;
    });
    if(n<=8&&totals[i]>0)s+='<text class="vl" x="'+cx+'" y="'+(y(totals[i])-5)+'" text-anchor="middle">'+(opt.vfmt||fmtNum)(totals[i])+'</text>';
    if(n<=8){
      s+='<text class="xl'+(d.isToday?' td':'')+'" x="'+cx+'" y="'+(H-m.b+15)+'" text-anchor="middle">'+WD[d.date.getDay()]+'</text><text class="xl'+(d.isToday?' td':'')+'" x="'+cx+'" y="'+(H-m.b+28)+'" text-anchor="middle">'+d.date.getDate()+'.</text>';
    }else if((n-1-i)%(n<=16?1:3)===0){
      s+='<text class="xl'+(d.isToday?' td':'')+'" x="'+cx+'" y="'+(H-m.b+16)+'" text-anchor="middle">'+d.date.getDate()+'.</text>';
    }
    var tipTxt=[dLabel(d.date)].concat(opt.tip(d)).join('|');
    s+='<rect class="hit" x="'+(m.l+slot*i)+'" y="'+m.t+'" width="'+slot+'" height="'+ph+'" data-tip="'+esc(tipTxt)+'"/>';
  });
  if(opt.avg>0){var ya=y(opt.avg);s+='<line class="avg" x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+ya+'" y2="'+ya+'"/>';}
  host.innerHTML=s+'</svg>';
}
function rhythmChart(host,days){
  var rows=days.slice(-14),rh=27,W=Math.max(260,host.clientWidth||320);
  var m={l:56,r:12,t:6,b:24},pw=W-m.l-m.r,H=m.t+rows.length*rh+m.b;
  var x=function(hr){return m.l+(hr/24)*pw;};
  var s='<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="Tagesrhythmus der Mahlzeiten und Windeln">';
  [0,6,12,18,24].forEach(function(hr){
    s+='<line class="'+(hr===0?'ax':'gr')+'" x1="'+x(hr)+'" x2="'+x(hr)+'" y1="'+m.t+'" y2="'+(H-m.b)+'"/><text x="'+x(hr)+'" y="'+(H-6)+'" text-anchor="'+(hr===0?'start':hr===24?'end':'middle')+'">'+hr+' Uhr</text>';
  });
  rows.forEach(function(d,r){
    var top=m.t+r*rh,cy=top+10;
    var d0=d.date.getTime(),d1=d0+DAY;
    events.forEach(function(e){
      if(e.type!=='schlaf')return;
      var s0=e.ts,s1=e.ts+(+e.min||0)*6e4;if(s1<=d0||s0>=d1)return;
      var xa=x((Math.max(s0,d0)-d0)/36e5),xb=x((Math.min(s1,d1)-d0)/36e5),nt=e.kind==='nacht',ds=describe(e);
      s+='<rect x="'+xa+'" y="'+(top+1)+'" width="'+Math.max(1,xb-xa)+'" height="'+(rh-3)+'" rx="3" fill="'+(nt?'var(--c-nacht)':'var(--c-nap)')+'" opacity=".3" data-tip="'+esc(ds.t+'|'+hhmm(e.ts)+' Uhr · '+ds.d)+'"/>';
    });
    s+='<text class="xl'+(d.isToday?' td':'')+'" x="'+(m.l-8)+'" y="'+(cy+4)+'" text-anchor="end">'+WD[d.date.getDay()]+' '+d.date.getDate()+'.</text>';
    d.feeds.forEach(function(e){
      var hr=(e.ts-d.date.getTime())/36e5,cx=x(Math.min(24,Math.max(0,hr))),ds=describe(e);
      var tipTxt=hhmm(e.ts)+' Uhr · '+ds.t+'|'+ds.d;
      if(e.type==='stillen')s+='<circle cx="'+cx+'" cy="'+cy+'" r="5" fill="var(--c-stillen)" stroke="var(--surface)" stroke-width="2"/>';
      else s+='<rect x="'+(cx-4.5)+'" y="'+(cy-4.5)+'" width="9" height="9" rx="2" fill="var(--c-flasche)" stroke="var(--surface)" stroke-width="2"/>';
      s+='<circle cx="'+cx+'" cy="'+cy+'" r="9" fill="transparent" data-tip="'+esc(tipTxt)+'"/>';
    });
    d.dia.forEach(function(e){
      var hr=(e.ts-d.date.getTime())/36e5,cx=x(Math.min(24,Math.max(0,hr)));
      var col=e.diaper==='nass'?'var(--c-windel)':'var(--c-stuhl)';
      s+='<rect x="'+(cx-1.5)+'" y="'+(top+17)+'" width="3" height="8" rx="1" fill="'+col+'"/><rect x="'+(cx-6)+'" y="'+(top+14)+'" width="12" height="13" fill="transparent" data-tip="'+esc(hhmm(e.ts)+' Uhr · Windel|'+(DIA[e.diaper]||''))+'"/>';
    });
  });
  host.innerHTML=s+'</svg>';
}
function niceStep(raw,min){var p=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/p;return Math.max(min,(f<=1?1:f<=2?2:f<=5?5:10)*p);}
var GROWTH={
  g:{key:'g',unit:'g',label:'Gewichtsverlauf in Gramm',birthKey:'birthWeight',minRange:100,minStep:50,hide:false,
    empty:'Sobald zwei Gewichte vorliegen, erscheint hier die Kurve. Das Geburtsgewicht trägst du in den Einstellungen ein.'},
  len:{key:'len',unit:'cm',label:'Verlauf der Körperlänge in Zentimetern',birthKey:'birthLength',minRange:4,minStep:.5,hide:true,
    empty:'Sobald zwei Längen vorliegen, erscheint hier die Kurve. Die Geburtslänge trägst du in den Einstellungen ein.'},
  head:{key:'head',unit:'cm',label:'Verlauf des Kopfumfangs in Zentimetern',birthKey:'birthHead',minRange:2,minStep:.5,hide:true,
    empty:'Sobald zwei Messungen vorliegen, erscheint hier die Kurve. Den Kopfumfang bei der Geburt trägst du in den Einstellungen ein.'}
};
function growthChart(host,subSel,o){
  var card=host.closest('article');
  var real=growth.filter(function(e){return +e[o.key]>0;});
  if(card)card.hidden=o.hide&&real.length===0;
  var pts=real.map(function(e){return {t:e.ts,v:+e[o.key]};});
  var bv=+settings[o.birthKey];
  if(bv>0&&settings.birth){var bt=new Date(settings.birth+'T12:00:00').getTime();if(isFinite(bt))pts.push({t:bt,v:bv,birth:true});}
  pts.sort(function(a,b){return a.t-b.t;});
  var sub=$(subSel),fmt=function(v){return o.unit==='cm'?fmtDec(v,1):fmtNum(v);};
  host.textContent='';
  if(pts.length<2){sub.textContent='';host.append(h('p',{class:'empty',text:o.empty}));return;}
  var last=pts[pts.length-1],prev=pts[pts.length-2],dv=last.v-prev.v;
  sub.textContent='Zuletzt '+fmt(last.v)+' '+o.unit+' ('+(dv>=0?'+':'−')+fmt(Math.abs(dv))+' '+o.unit+' seit '+(prev.birth?'der Geburt':'der vorigen Messung')+')';
  var W=Math.max(260,host.clientWidth||320),H=200,m={l:44,r:16,t:22,b:28},pw=W-m.l-m.r,ph=H-m.t-m.b;
  var t0=pts[0].t,t1=Math.max(last.t,t0+6*DAY);
  var vs=pts.map(function(p){return p.v;}),mn=Math.min.apply(null,vs),mx=Math.max.apply(null,vs);
  var st=niceStep(Math.max(mx-mn,o.minRange)/3,o.minStep),y0=Math.floor((mn-st*.3)/st)*st,y1=Math.ceil((mx+st*.3)/st)*st;
  var X=function(t){return m.l+((t-t0)/(t1-t0))*pw;},Y=function(v){return m.t+ph-((v-y0)/(y1-y0))*ph;};
  var s='<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="'+esc(o.label)+'">';
  for(var g=y0;g<=y1+1e-9;g+=st){s+='<line class="'+(g===y0?'ax':'gr')+'" x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+Y(g)+'" y2="'+Y(g)+'"/><text x="'+(m.l-6)+'" y="'+(Y(g)+4)+'" text-anchor="end">'+(st<1?fmtDec(g,1):fmtNum(g))+'</text>';}
  for(var i=0;i<4;i++){var tt=t0+(t1-t0)*i/3,dd=new Date(tt);s+='<text x="'+X(tt)+'" y="'+(H-8)+'" text-anchor="'+(i===0?'start':i===3?'end':'middle')+'">'+dd.getDate()+'. '+MON[dd.getMonth()]+'</text>';}
  s+='<polyline class="ln" points="'+pts.map(function(p){return X(p.t)+','+Y(p.v);}).join(' ')+'"/>';
  pts.forEach(function(p,k){
    var d=new Date(p.t),tipTxt=(p.birth?'Geburt':dLabel(d)+' '+hhmm(p.t))+'|'+fmt(p.v)+' '+o.unit;
    s+='<circle cx="'+X(p.t)+'" cy="'+Y(p.v)+'" r="4.5" fill="'+(p.birth?'var(--surface)':'var(--c-gewicht)')+'" stroke="'+(p.birth?'var(--c-gewicht)':'var(--surface)')+'" stroke-width="2"/><circle cx="'+X(p.t)+'" cy="'+Y(p.v)+'" r="12" fill="transparent" data-tip="'+esc(tipTxt)+'"/>';
    if(k===pts.length-1)s+='<text class="vl" x="'+X(p.t)+'" y="'+(Y(p.v)-10)+'" text-anchor="'+(X(p.t)>W-60?'end':'middle')+'">'+fmt(p.v)+' '+o.unit+'</text>';
  });
  host.innerHTML=s+'</svg>';
}
/* ---------- Babys: Umschalter und Vergleich ---------- */
var cmp={target:null,cache:null,token:0};
function babyLabel(b){var cur=window.TrinkBabies&&window.TrinkBabies.current();var n=(b.id===cur?(settings.name||b.name):b.name)||'';return n.trim()||'Baby';}
function renderBabies(){
  var box=$('#babies'),B=window.TrinkBabies;
  if(!box)return;
  var list=B?B.list():[],cur=B?B.current():null;
  if(list.length<2){box.hidden=true;return;}
  box.hidden=false;box.textContent='';
  list.forEach(function(b){
    box.append(h('button',{type:'button',class:'bchip','aria-pressed':b.id===cur?'true':'false',text:babyLabel(b),onclick:function(){if(b.id!==cur)B.set(b.id);}}));
  });
}
function mlSeries(evs,birth){
  var tot={},first=Infinity,last=-Infinity;
  evs.forEach(function(e){
    if(e.type!=='flasche'||!(+e.ml>0))return;
    var k=dayKey(e.ts),t=startOfDay(e.ts).getTime();
    tot[k]=(tot[k]||0)+(+e.ml);
    if(t<first)first=t;if(t>last)last=t;
  });
  if(first===Infinity)return {pts:[],hasBirth:false};
  var b=birth?new Date(birth+'T00:00:00').getTime():NaN,hasBirth=isFinite(b),o=hasBirth?b:first;
  var today=startOfDay(Date.now()).getTime(),pts=[];
  Object.keys(tot).forEach(function(k){
    var d=new Date(k+'T00:00:00').getTime();
    if(d===first||d===last||d>=today)return;
    pts.push({day:Math.round((d-o)/DAY),ml:tot[k]});
  });
  pts.sort(function(a,b){return a.day-b.day;});
  pts.forEach(function(p,i){
    var s=0,n=0;
    for(var j=i;j>=0&&p.day-pts[j].day<7;j--){s+=pts[j].ml;n++;}
    p.avg=s/n;
  });
  return {pts:pts,hasBirth:hasBirth};
}
function loadCmp(curId,otherId){
  var key=curId+'>'+otherId,c=cmp.cache,B=window.TrinkBabies;
  if(c&&c.key===key&&Date.now()-c.at<30000)return Promise.resolve(c);
  return Promise.all([B.events(curId,'flasche'),B.events(otherId,'flasche')]).then(function(r){
    cmp.cache={key:key,at:Date.now(),a:r[0],b:r[1]};return cmp.cache;
  });
}
function cmpChart(host,A,Bs,nA,nB){
  var all=A.pts.concat(Bs.pts),maxDay=Math.max.apply(null,all.map(function(p){return p.day;})),minDay=Math.min(0,Math.min.apply(null,all.map(function(p){return p.day;})));
  var maxMl=Math.max.apply(null,all.map(function(p){return p.ml;})),ys=yScale(maxMl,50);
  var W=Math.max(260,host.clientWidth||320),H=230,m={l:42,r:10,t:14,b:40},pw=W-m.l-m.r,ph=H-m.t-m.b,span=maxDay-minDay+1;
  var X=function(d){return m.l+((d-minDay+.5)/span)*pw;},Y=function(v){return m.t+ph-(v/ys.max)*ph;};
  var s='<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="Flaschenmenge pro Tag im Vergleich nach Lebenstag">';
  for(var g=0;g<=ys.max+1e-9;g+=ys.step){s+='<line class="'+(g===0?'ax':'gr')+'" x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+Y(g)+'" y2="'+Y(g)+'"/><text x="'+(m.l-6)+'" y="'+(Y(g)+4)+'" text-anchor="end">'+fmtNum(g)+'</text>';}
  var step=[7,14,28,56,84,168].filter(function(x){return (maxDay-minDay)/x*36<=pw;})[0]||168;
  for(var d=Math.ceil(minDay/step)*step;d<=maxDay;d+=step){s+='<text x="'+X(d)+'" y="'+(H-m.b+15)+'" text-anchor="middle">'+d+'</text>';}
  s+='<text x="'+(m.l+pw/2)+'" y="'+(H-6)+'" text-anchor="middle">Lebenstag</text>';
  var byDay={};
  [[A,'a'],[Bs,'b']].forEach(function(x){x[0].pts.forEach(function(p){(byDay[p.day]=byDay[p.day]||{})[x[1]]=p;});});
  [[A,'var(--c-flasche)'],[Bs,'var(--c-gewicht)']].forEach(function(x){
    x[0].pts.forEach(function(p){s+='<circle cx="'+X(p.day)+'" cy="'+Y(p.ml)+'" r="2.5" fill="'+x[1]+'" opacity=".4"/>';});
  });
  [[A,'var(--c-flasche)'],[Bs,'var(--c-gewicht)']].forEach(function(x){
    if(x[0].pts.length>1)s+='<polyline fill="none" stroke="'+x[1]+'" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="'+x[0].pts.map(function(p){return X(p.day)+','+Y(p.avg);}).join(' ')+'"/>';
    else if(x[0].pts.length===1)s+='<circle cx="'+X(x[0].pts[0].day)+'" cy="'+Y(x[0].pts[0].avg)+'" r="4" fill="'+x[1]+'"/>';
  });
  var slot=pw/span;
  Object.keys(byDay).forEach(function(k){
    var d=+k,r=byDay[k],tip=['Lebenstag '+d];
    if(r.a)tip.push(nA+': '+fmtNum(r.a.ml)+' ml');
    if(r.b)tip.push(nB+': '+fmtNum(r.b.ml)+' ml');
    s+='<rect class="hit" x="'+(X(d)-slot/2)+'" y="'+m.t+'" width="'+slot+'" height="'+ph+'" data-tip="'+esc(tip.join('|'))+'"/>';
  });
  host.innerHTML=s+'</svg>';
}
function weekMeans(S){
  var w={};
  S.pts.forEach(function(p){var k=Math.floor(p.day/7)+1;(w[k]=w[k]||[]).push(p.ml);});
  return w;
}
function renderCompare(){
  var card=$('#cmpCard'),B=window.TrinkBabies;
  if(!card)return;
  var list=B?B.list():[],cur=B?B.current():null,others=list.filter(function(b){return b.id!==cur;});
  if(!others.length){card.hidden=true;return;}
  card.hidden=false;
  if(!cmp.target||!others.some(function(o){return o.id===cmp.target;}))cmp.target=others[0].id;
  var other=others.filter(function(o){return o.id===cmp.target;})[0],curB=list.filter(function(b){return b.id===cur;})[0]||{id:cur,name:'',birth:''};
  var nA=babyLabel(curB),nB=babyLabel(other);
  $('#cmpTitle').textContent='Vergleich mit '+nB;
  var pick=$('#cmpPick');pick.textContent='';pick.hidden=others.length<2;
  others.forEach(function(o){pick.append(h('button',{type:'button',class:'bchip','aria-pressed':o.id===cmp.target?'true':'false',text:babyLabel(o),onclick:function(){cmp.target=o.id;renderCompare();}}));});
  var tok=++cmp.token,host=$('#ch-cmp');
  loadCmp(cur,cmp.target).then(function(c){
    if(tok!==cmp.token)return;
    var A=mlSeries(c.a,settings.birth||curB.birth),Bs=mlSeries(c.b,other.birth);
    var sub=$('#sub-cmp'),foot=$('#cmpFoot'),det=$('#cmpDet');
    legend('#lg-cmp',[{label:nA,color:'var(--c-flasche)',shape:'bar'},{label:nB,color:'var(--c-gewicht)',shape:'bar'}]);
    if(!A.pts.length&&!Bs.pts.length){sub.textContent='';foot.textContent='';det.hidden=true;host.textContent='';host.append(h('p',{class:'empty',text:'Zum Vergleichen fehlen noch vollständige Tage mit Flaschenmengen.'}));return;}
    var da={},both=[];
    A.pts.forEach(function(p){da[p.day]=p.ml;});
    Bs.pts.forEach(function(p){if(da[p.day]!=null)both.push([da[p.day],p.ml,p.day]);});
    if(both.length>=3){
      var ma=mean(both.map(function(x){return x[0];})),mb=mean(both.map(function(x){return x[1];}));
      sub.textContent='Im gleichen Alter (Lebenstag '+both[0][2]+' bis '+both[both.length-1][2]+', '+both.length+' Tage): '+nA+' Ø '+fmtNum(ma)+' ml, '+nB+' Ø '+fmtNum(mb)+' ml pro Tag.';
    }else sub.textContent='Flaschenmenge pro Tag, aufgetragen nach Lebenstag.';
    cmpChart(host,A,Bs,nA,nB);
    foot.textContent='Linien: Mittelwert der letzten 7 Tage, Punkte: einzelne Tage. Nur Flaschenmengen, Stillmahlzeiten sind nicht enthalten. Der erste und der letzte erfasste Tag sowie heute zählen nicht, weil sie meist unvollständig sind.'+((A.pts.length&&!A.hasBirth)||(Bs.pts.length&&!Bs.hasBirth)?' Ohne Geburtstag zählt der erste erfasste Tag als Lebenstag 0.':'');
    var wa=weekMeans(A),wb=weekMeans(Bs),weeks=Object.keys(wa).concat(Object.keys(wb)).map(Number).filter(function(v,i,a){return a.indexOf(v)===i;}).sort(function(x,y){return x-y;});
    var t=$('#tbl-cmp');t.textContent='';
    t.append(h('thead',null,h('tr',null,['Woche',nA,nB,'Differenz'].map(function(x){return h('th',{scope:'col',text:x});}))));
    var tb=h('tbody');
    weeks.forEach(function(k){
      var a=wa[k]?mean(wa[k]):null,b=wb[k]?mean(wb[k]):null;
      var d=a!=null&&b!=null?Math.round(a-b):null;
      tb.append(h('tr',null,[String(k),a==null?'–':fmtNum(a)+' ml',b==null?'–':fmtNum(b)+' ml',d==null?'–':(d>=0?'+':'−')+fmtNum(Math.abs(d))+' ml'].map(function(x,i){return h(i?'td':'th',{scope:i?null:'row',text:x});})));
    });
    t.append(tb);det.hidden=false;
  }).catch(function(){if(tok!==cmp.token)return;host.textContent='';host.append(h('p',{class:'empty',text:'Der Vergleich konnte nicht geladen werden.'}));});
}
function renderStats(){
  var days=buildDays(range),active=function(d){return d.stillen+d.flasche+d.diapers>0;};
  var any=days.some(function(d){return active(d)||d.spucken||d.vitd||d.nap||d.night||d.brei||d.temp||d.medi;});
  $('#statsEmpty').hidden=any||growth.length>0;
  $('#statsBody').hidden=!any&&!growth.length;
  if(!any&&!growth.length)return;
  var base=days.filter(function(d){return !d.isToday&&active(d);});
  if(!base.length)base=days.filter(active);
  var avg=function(f){return base.length?base.reduce(function(s,d){return s+f(d);},0)/base.length:0;};
  var feeds=[];days.forEach(function(d){feeds=feeds.concat(d.feeds);});
  var g=mean(gaps(feeds));
  var sleepTot=days.reduce(function(s,d){return s+d.nap+d.night;},0),sleepDays=days.filter(function(d){return !d.isToday&&d.nap+d.night>0;});
  if(!sleepDays.length)sleepDays=days.filter(function(d){return d.nap+d.night>0;});
  var avgS=function(f){return sleepDays.length?sleepDays.reduce(function(s,d){return s+f(d);},0)/sleepDays.length:0;};
  var k=$('#kpis');k.textContent='';
  [[fmtDec(avg(function(d){return d.stillen+d.flasche;})),'Mahlzeiten pro Tag'],[g==null?'–':fmtDur(g),'Abstand zwischen Mahlzeiten'],
   [avg(function(d){return d.ml;})>0?fmtNum(avg(function(d){return d.ml;}))+' ml':'–','Flasche pro Tag'],[fmtDec(avg(function(d){return d.diapers;})),'Windeln pro Tag']].concat(sleepTot>0?[[fmtDec(avgS(function(d){return d.nap+d.night;})/60,1)+' Std','Schlaf pro Tag'],[fmtDec(avgS(function(d){return d.night;})/60,1)+' Std','Davon nachts']]:[]).forEach(function(p){
    k.append(h('div',{class:'card kpi'},h('dd',{text:p[0]}),h('dt',{text:p[1]})));
  });
  $('#kpiFoot').textContent=base.length?'Durchschnitt über '+base.length+(base.length===1?' Tag':' Tage')+(base.some(function(d){return d.isToday;})?(anchor?' (letzter Tag unvollständig)':' (heute noch unvollständig)'):(anchor?', ohne den letzten Tag':', ohne den heutigen Tag'))+'. Abstände über 8 Std gelten als Pause und zählen nicht.':'';

  var n=function(d){return d.stillen+d.flasche;};
  $('#sub-meals').textContent='Ø '+fmtDec(avg(n))+' pro Tag';
  legend('#lg-meals',[{label:'Stillen',color:'var(--c-stillen)',shape:'bar'},{label:'Flasche',color:'var(--c-flasche)',shape:'bar'}]);
  barChart($('#ch-meals'),days,[{val:function(d){return d.stillen;},color:'var(--c-stillen)'},{val:function(d){return d.flasche;},color:'var(--c-flasche)'}],
    {label:'Mahlzeiten pro Tag, gestapelt nach Stillen und Flasche',avg:avg(n),tip:function(d){return ['Stillen: '+d.stillen,'Flasche: '+d.flasche,'Gesamt: '+(d.stillen+d.flasche)];}});

  var mlHost=$('#ch-ml'),totalMl=days.reduce(function(s,d){return s+d.ml;},0);
  if(totalMl>0){
    $('#sub-ml').textContent='Ø '+fmtNum(avg(function(d){return d.ml;}))+' ml pro Tag (gestrichelt)';
    barChart(mlHost,days,[{val:function(d){return d.ml;},color:'var(--c-flasche)'}],{label:'Flaschenmenge pro Tag in Millilitern',avg:avg(function(d){return d.ml;}),minStep:10,
      tip:function(d){return [fmtNum(d.ml)+' ml','in '+d.flasche+(d.flasche===1?' Flasche':' Flaschen')];}});
  }else{$('#sub-ml').textContent='';mlHost.textContent='';mlHost.append(h('p',{class:'empty',text:'In diesem Zeitraum gab es keine Flasche.'}));}

  var minHost=$('#ch-min'),totalMin=days.reduce(function(s,d){return s+d.min;},0);
  if(totalMin>0){
    $('#sub-min').textContent='Ø '+fmtNum(avg(function(d){return d.min;}))+' Min pro Tag (gestrichelt)';
    barChart(minHost,days,[{val:function(d){return d.min;},color:'var(--c-stillen)'}],{label:'Stillzeit pro Tag in Minuten',avg:avg(function(d){return d.min;}),minStep:5,
      tip:function(d){return [fmtNum(d.min)+' Min','in '+d.stillen+(d.stillen===1?' Mahlzeit':' Mahlzeiten')];}});
  }else{$('#sub-min').textContent='';minHost.textContent='';minHost.append(h('p',{class:'empty',text:'In diesem Zeitraum wurde nicht gestillt.'}));}

  var sc=$('#sleepCard');sc.hidden=sleepTot<=0;
  if(sleepTot>0){
    $('#sub-sleep').textContent='Ø '+fmtDur(avgS(function(d){return d.nap+d.night;}))+' pro Tag, davon nachts '+fmtDur(avgS(function(d){return d.night;}));
    legend('#lg-sleep',[{label:'Nachtschlaf',color:'var(--c-nacht)',shape:'bar'},{label:'Nickerchen',color:'var(--c-nap)',shape:'bar'}]);
    barChart($('#ch-sleep'),days,[{val:function(d){return d.night/60;},color:'var(--c-nacht)'},{val:function(d){return d.nap/60;},color:'var(--c-nap)'}],
      {label:'Schlaf pro Tag in Stunden, gestapelt nach Nachtschlaf und Nickerchen',avg:avgS(function(d){return d.nap+d.night;})/60,minStep:1,vfmt:function(v){return fmtDec(v,1);},
       tip:function(d){return ['Gesamt: '+fmtDur(d.nap+d.night),'Nacht: '+fmtDur(d.night),'Nickerchen: '+fmtDur(d.nap)+(d.naps?' ('+d.naps+'×)':'')];}});
  }
  renderHealth(days);
  legend('#lg-rhythm',[{label:'Stillen',color:'var(--c-stillen)'},{label:'Flasche',color:'var(--c-flasche)',shape:'square'},{label:'Windel nass',color:'var(--c-windel)',shape:'tick'},{label:'Windel mit Stuhl',color:'var(--c-stuhl)',shape:'tick'}].concat(sleepTot>0?[{label:'Nachtschlaf',color:'var(--c-nacht)',shape:'bar'},{label:'Nickerchen',color:'var(--c-nap)',shape:'bar'}]:[]));
  rhythmChart($('#ch-rhythm'),days);

  $('#sub-dia').textContent='Ø '+fmtDec(avg(function(d){return d.diapers;}))+' pro Tag';
  legend('#lg-dia',[{label:'Nur nass',color:'var(--c-windel)',shape:'bar'},{label:'Mit Stuhl',color:'var(--c-stuhl)',shape:'bar'}]);
  barChart($('#ch-dia'),days,[{val:function(d){return d.nass;},color:'var(--c-windel)'},{val:function(d){return d.stuhl;},color:'var(--c-stuhl)'}],
    {label:'Windeln pro Tag, gestapelt nach nass und mit Stuhl',avg:avg(function(d){return d.diapers;}),tip:function(d){return ['Nur nass: '+d.nass,'Mit Stuhl: '+d.stuhl,'Gesamt: '+d.diapers];}});

  growthChart($('#ch-w'),'#sub-w',GROWTH.g);
  growthChart($('#ch-l'),'#sub-l',GROWTH.len);
  growthChart($('#ch-h'),'#sub-h',GROWTH.head);

  var t=$('#tbl');t.textContent='';
  t.append(h('thead',null,h('tr',null,['Tag','Stillen','Flasche','ml','Min','Nass','Stuhl','Spucken','Schlaf'].map(function(c){return h('th',{scope:'col',text:c});}))));
  var tb=h('tbody');
  days.slice().reverse().forEach(function(d){
    tb.append(h('tr',null,[dLabel(d.date),d.stillen,d.flasche,fmtNum(d.ml),d.min,d.nass,d.stuhl,d.spucken,d.nap+d.night>0?fmtDec((d.nap+d.night)/60,1)+' Std':'–'].map(function(c,i){return h(i?'td':'th',{scope:i?null:'row',text:String(c)});})));
  });
  t.append(tb);
  renderCompare();
  $('#btnCsv').hidden=!dl;
}
document.querySelectorAll('input[name=range]').forEach(function(r){r.addEventListener('change',function(){range=+r.value;renderStats();});});

/* ---------- Eingabeblatt ---------- */
var sheetType=null,lastFocus=null;
function seg(name,label,opts,val){
  var row=h('div',{class:'seg-row'});
  opts.forEach(function(o){var id=name+'-'+o[0];row.append(h('input',{type:'radio',name:name,id:id,value:o[0],checked:o[0]===val}),h('label',{for:id,text:o[1]}));});
  return h('fieldset',{class:'seg'},h('legend',{text:label}),row);
}
function numField(id,label,o){
  var inp=h('input',{id:id,type:'number',inputmode:o.dec?'decimal':'numeric',min:o.min,max:o.max,step:o.dec?'any':1,value:o.val==null?'':o.val});
  var bump=function(d){if(inp.value===''&&o.start!=null){inp.value=o.start;return;}inp.value=Math.round(Math.min(o.max,Math.max(o.min,(+inp.value||0)+d))*10)/10;};
  var box=h('div',{class:'field'},h('label',{for:id,text:label}),
    h('div',{class:'stepper'},h('button',{type:'button','aria-label':label+' verringern',text:'−',onclick:function(){bump(-o.inc);}}),inp,
      h('button',{type:'button','aria-label':label+' erhöhen',text:'+',onclick:function(){bump(o.inc);}}),h('span',{class:'unit',text:o.unit})));
  if(o.chips)box.append(h('div',{class:'chips'},o.chips.map(function(c){return h('button',{type:'button',class:'chip',text:String(c),onclick:function(){inp.value=c;}});})));
  return box;
}
function timeField(){
  var inp=h('input',{id:'f-time',type:'datetime-local',value:toLocalInput(Date.now())});
  return h('div',{class:'field'},h('label',{for:'f-time',text:'Zeitpunkt'}),h('div',{class:'row2'},inp,h('button',{type:'button',class:'ghost',text:'Jetzt',onclick:function(){inp.value=toLocalInput(Date.now());}})));
}
function noteField(){return h('div',{class:'field'},h('label',{for:'f-note',text:'Notiz (optional)'}),h('input',{id:'f-note',type:'text',maxlength:'200',placeholder:'z. B. unruhig, hat gut getrunken'}));}
function curSide(){var c=document.querySelector('input[name=side]:checked');return c?c.value:'links';}

function openSheet(type,ev){
  if(type!=='settings'&&!canWrite)return;
  editing=ev||null;
  lastFocus=document.activeElement;sheetType=type;
  var box=$('#sheetFields');box.textContent='';$('#sheetErr').hidden=true;$('#sheetSave').disabled=false;
  $('#sheetTitle').textContent=type==='settings'?'Einstellungen':(editing?'Bearbeiten: ':'')+TYPES[type].label;
  if(type==='stillen'){
    var ls=lastOf('stillen'),next=ls&&ls.side==='links'?'rechts':'links';
    var side=timer&&timer.side?timer.side:next;
    box.append(seg('side','Seite',[['links','Links'],['rechts','Rechts'],['beide','Beide']],side));
    if(ls&&!timer)box.lastChild.append(h('p',{class:'hintl',text:'Zuletzt: '+(SIDE[ls.side]||'–')+'. Vorgeschlagen ist die andere Seite.'}));
    var out=h('output',{id:'tOut',text:'00:00'}),tb=h('button',{type:'button',class:'ghost',id:'tBtn'});
    box.append(h('div',{class:'timer'},out,tb));
    box.append(numField('f-min','Dauer',{min:1,max:180,val:10,inc:1,unit:'Min',chips:[5,10,15,20,30]}));
    tb.addEventListener('click',function(){
      if(!timer){timer={start:Date.now(),side:curSide()};saveTimer();closeSheet();renderBanner();toast('Timer läuft. Zum Beenden oben auf „Stillen läuft“ tippen.');}
      else{var el=Date.now()-timer.start;$('#f-min').value=Math.min(180,Math.max(1,Math.round(el/6e4)));$('#f-time').value=toLocalInput(timer.start);timer=null;saveTimer();renderBanner();updateTimerUi();}
    });
    box.append(timeField(),noteField());
    updateTimerUi();
  }else if(type==='flasche'){
    var lf=lastOf('flasche');
    box.append(numField('f-ml','Menge',{min:1,max:400,val:lf&&+lf.ml>0?+lf.ml:60,inc:10,unit:'ml',chips:[30,50,60,80,100,120,150]}),
      seg('kind','Nahrung',[['muttermilch','Muttermilch'],['pre','Pre-Nahrung'],['folge','Folgemilch']],lf&&lf.kind?lf.kind:'pre'),timeField(),noteField());
  }else if(type==='windel'){
    box.append(seg('diaper','Inhalt',[['nass','Nass'],['stuhl','Stuhl'],['beides','Beides']],'nass'),timeField(),noteField());
  }else if(type==='wachstum'){
    var lastV=function(k){for(var i=growth.length-1;i>=0;i--)if(+growth[i][k]>0)return +growth[i][k];return 0;};
    box.append(h('p',{class:'hintl',text:'Alles ist optional. Trage ein, was du gemessen hast. Beim ersten Tippen auf + oder − startet das Feld beim letzten bekannten Wert.'}),
      numField('f-g','Gewicht',{min:500,max:25000,val:'',start:lastV('g')||+settings.birthWeight||3400,inc:10,unit:'g'}),
      numField('f-len','Körperlänge',{min:30,max:130,val:'',start:lastV('len')||+settings.birthLength||50,inc:0.5,unit:'cm',dec:true}),
      numField('f-head','Kopfumfang',{min:25,max:60,val:'',start:lastV('head')||+settings.birthHead||35,inc:0.5,unit:'cm',dec:true}),
      timeField(),noteField());
  }else if(type==='spucken'){
    box.append(seg('amount','Menge',[['wenig','Wenig'],['mittel','Mittel'],['viel','Viel']],'wenig'),timeField(),noteField());
  }else if(type==='vitd'){
    box.append(h('p',{class:'hint',text:'Hält fest, dass die Vitamin-D-Gabe erledigt ist.'}),timeField(),noteField());
  }else if(type==='temp'){
    tempSheet(box);
  }else if(type==='medi'){
    mediSheet(box);
  }else if(type==='schlaf'){
    sleepSheet(box);
  }else if(type==='beikost'){
    beikostSheet(box);
  }else if(type==='settings'){
    box.append(h('div',{class:'field'},h('label',{for:'f-name',text:'Name des Babys'}),h('input',{id:'f-name',type:'text',maxlength:'40',value:settings.name||''})),
      h('div',{class:'field'},h('label',{for:'f-birth',text:'Geburtstag'}),h('input',{id:'f-birth',type:'date',value:settings.birth||''})),
      numField('f-bw','Geburtsgewicht',{min:0,max:9000,val:+settings.birthWeight>0?+settings.birthWeight:'',start:3400,inc:10,unit:'g'}),
      numField('f-bl','Geburtslänge',{min:30,max:70,val:+settings.birthLength>0?+settings.birthLength:'',start:50,inc:0.5,unit:'cm',dec:true}),
      numField('f-bh','Kopfumfang bei der Geburt',{min:25,max:50,val:+settings.birthHead>0?+settings.birthHead:'',start:35,inc:0.5,unit:'cm',dec:true}));
    box.append(h('p',{class:'hintl',text:'Mit dem Geburtstag zeigt die Seite das Alter an. Die Geburtswerte sind der Startpunkt der Wachstumskurven.'}));
  }
  if(editing)prefillEdit(editing);
  $('#sheetSave').textContent=editing?'Änderung speichern':'Speichern';
  $('#sheetSave').hidden=false;
  $('#sheetBack').hidden=false;document.body.classList.add('lock');
  var first=box.querySelector('input:not([type=radio]):not([type=date]),input[type=radio]:checked');
  if(first&&type!=='stillen')first.focus({preventScroll:true});
}
function closeSheet(){$('#sheetBack').hidden=true;document.body.classList.remove('lock');sheetType=null;if(lastFocus&&lastFocus.focus)try{lastFocus.focus({preventScroll:true});}catch(e){}}
function updateTimerUi(){
  var out=$('#tOut'),btn=$('#tBtn');if(!out||!btn)return;
  if(timer){var s=Math.max(0,Math.floor((Date.now()-timer.start)/1000));out.textContent=pad(Math.floor(s/60))+':'+pad(s%60);btn.textContent='Stoppen und übernehmen';}
  else{btn.textContent='Timer starten';}
}
$('#sheetClose').addEventListener('click',closeSheet);
$('#sheetBack').addEventListener('click',function(e){if(e.target===this)closeSheet();});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!$('#sheetBack').hidden)closeSheet();});
$('#btnSettings').addEventListener('click',function(){if(!db){return;}openSheet('settings');});

$('#sheetForm').addEventListener('submit',function(e){
  e.preventDefault();
  var err=$('#sheetErr'),btn=$('#sheetSave');
  var fail=function(m){err.textContent=m;err.hidden=false;btn.disabled=false;};
  err.hidden=true;
  if(!db)return fail('Speichern ist in dieser Ansicht nicht möglich.');
  var f=e.target;
  if(sheetType==='settings'){
    var bwv=+$('#f-bw').value,blv=+$('#f-bl').value,bhv=+$('#f-bh').value;
    if((bwv>0&&(bwv<500||bwv>9000))||(blv>0&&(blv<30||blv>70))||(bhv>0&&(bhv<25||bhv>50)))return fail('Bitte Geburtswerte im üblichen Bereich eintragen.');
    btn.disabled=true;
    db.doc('settings/baby').set({name:$('#f-name').value.trim().slice(0,40),birth:$('#f-birth').value||'',birthWeight:bwv>0?Math.round(bwv):0,birthLength:blv>0?Math.round(blv*10)/10:0,birthHead:bhv>0?Math.round(bhv*10)/10:0})
      .then(function(){closeSheet();toast('Einstellungen gespeichert');}).catch(function(){fail('Speichern hat nicht geklappt. Bitte noch einmal versuchen.');});
    return;
  }
  var ts=new Date($('#f-time').value).getTime();
  if(!isFinite(ts))return fail('Bitte einen gültigen Zeitpunkt eintragen.');
  if(editing&&$('#f-time').value===toLocalInput(editing.ts))ts=editing.ts;
  if(ts>Date.now()+6e5)return fail('Der Zeitpunkt liegt in der Zukunft.');
  var ev={type:editing?editing.type:sheetType,ts:ts},msg='',clearSleep=false;
  var note=$('#f-note')?$('#f-note').value.trim().slice(0,200):'';
  if(sheetType==='stillen'){
    var mn=Math.round(+$('#f-min').value);if(!(mn>=1&&mn<=180))return fail('Die Dauer muss zwischen 1 und 180 Minuten liegen.');
    ev.side=f.elements.side.value;ev.min=mn;msg='Stillen '+mn+' Min gespeichert';
  }else if(sheetType==='flasche'){
    var ml=Math.round(+$('#f-ml').value);if(!(ml>=1&&ml<=400))return fail('Die Menge muss zwischen 1 und 400 ml liegen.');
    ev.ml=ml;ev.kind=f.elements.kind.value;msg='Flasche '+ml+' ml gespeichert';
  }else if(sheetType==='windel'){ev.diaper=f.elements.diaper.value;msg='Windel gespeichert';}
  else if(sheetType==='wachstum'){
    var gv=$('#f-g').value,lv=$('#f-len').value,hv=$('#f-head').value;
    if(gv===''&&lv===''&&hv==='')return fail('Bitte mindestens einen Wert eintragen.');
    if(gv!==''){var g=Math.round(+gv);if(!(g>=500&&g<=25000))return fail('Das Gewicht muss zwischen 500 und 25.000 g liegen.');ev.g=g;}
    if(lv!==''){var ln=Math.round(+lv*10)/10;if(!(ln>=30&&ln<=130))return fail('Die Länge muss zwischen 30 und 130 cm liegen.');ev.len=ln;}
    if(hv!==''){var hd=Math.round(+hv*10)/10;if(!(hd>=25&&hd<=60))return fail('Der Kopfumfang muss zwischen 25 und 60 cm liegen.');ev.head=hd;}
    msg='Wachstum gespeichert';
  }else if(sheetType==='spucken'){ev.amount=f.elements.amount.value;msg='Spucken gespeichert';}
  else if(sheetType==='vitd'){msg='Vitamin D gespeichert';}
  else if(sheetType==='temp'){
    var cv=$('#f-c').value;if(cv==='')return fail('Bitte die Temperatur eintragen.');
    var cc=Math.round(+cv*10)/10;if(!(cc>=34&&cc<=43))return fail('Die Temperatur muss zwischen 34 und 43 °C liegen.');
    ev.c=cc;ev.where=f.elements.where.value;msg='Temperatur '+fmtC(cc)+' gespeichert'+(cc>=38?'. Das ist Fieber.':'');
  }else if(sheetType==='medi'){
    var mn2=$('#f-mname').value.trim();if(!mn2)return fail('Bitte den Namen des Medikaments eintragen.');
    var lm2=lastMedi(mn2);ev.name=(lm2&&lm2.name?lm2.name:mn2).slice(0,60);var ds2=$('#f-dose').value.trim();if(ds2)ev.dose=ds2.slice(0,40);msg=ev.name+' gespeichert';
  }
  else if(sheetType==='beikost'){var bgv=$('#f-bg').value;if(bgv!==''){var bg=Math.round(+bgv);if(!(bg>=5&&bg<=600))return fail('Die Menge muss zwischen 5 und 600 g liegen.');ev.g=bg;}msg='Beikost gespeichert';}
  else if(sheetType==='schlaf'){
    var en=new Date($('#f-end').value).getTime();
    if(!isFinite(en))return fail('Bitte eintragen, wann das Baby aufgewacht ist.');
    if(en>Date.now()+6e5)return fail('Der Zeitpunkt liegt in der Zukunft.');
    var dm=Math.round((en-ts)/6e4),sk=f.elements.skind.value;
    if(editing&&ts===editing.ts&&$('#f-end').value===toLocalInput(editing.ts+(+editing.min||0)*6e4))dm=+editing.min;
    if(dm<1)return fail('„Aufgewacht“ muss nach „Eingeschlafen“ liegen.');
    if(dm>(sk==='nacht'?960:480))return fail(sk==='nacht'?'Eine Nacht darf höchstens 16 Stunden dauern.':'Ein Nickerchen darf höchstens 8 Stunden dauern.');
    ev.kind=sk;ev.min=dm;
    if(sk==='nacht'){
      var wv=$('#f-wach').value,nv=$('#f-n').value;
      if(wv!==''){var wm=Math.round(+wv);if(!(wm>=0&&wm<dm))return fail('„Davon wach“ muss kürzer als die Schlafzeit sein.');if(wm>0)ev.wach=wm;}
      if(nv!==''){var nn=Math.round(+nv);if(!(nn>=0&&nn<=30))return fail('Die Zahl der Wachphasen muss zwischen 0 und 30 liegen.');if(nn>0)ev.n=nn;}
    }
    clearSleep=true;msg=(sk==='nacht'?'Nachtschlaf ':'Nickerchen ')+fmtDur(dm)+' gespeichert';
  }
  if(note)ev.note=note;
  btn.disabled=true;
  if(editing){
    var ed=editing,old=Object.assign({},ed);delete old.id;
    db.collection('events').doc(ed.id).update(ev).then(function(){closeSheet();toast('Änderung gespeichert',function(){db.collection('events').doc(ed.id).update(old).catch(function(){});});}).catch(function(){fail('Speichern hat nicht geklappt. Bitte noch einmal versuchen.');});
    return;
  }
  db.collection('events').add(ev).then(function(ref){
    if(clearSleep){sleepTimer=null;saveSleepTimer();renderSleepBanner();}
    closeSheet();
    toast(msg,function(){ref.delete().catch(function(){});});
  }).catch(function(){fail('Speichern hat nicht geklappt. Bitte noch einmal versuchen.');});
});

/* ---------- CSV ---------- */
$('#btnCsv').addEventListener('click',function(){
  if(!dl)return;
  var q=function(v){v=v==null?'':String(v);return /[";\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
  var rows=[['Datum','Uhrzeit','Art','Seite','Dauer (Min)','Menge (ml)','Nahrung','Windel','Gewicht oder Beikost (g)','Länge (cm)','Kopfumfang (cm)','Spucken','Nachts wach (Min)','Wachphasen','Temperatur (°C)','Medikament','Notiz','Erfasst von']];
  events.slice().sort(function(a,b){return a.ts-b.ts;}).forEach(function(e){
    var d=new Date(e.ts);
    rows.push([pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear(),hhmm(e.ts),TYPES[e.type]?TYPES[e.type].label:e.type,SIDE[e.side]||'',e.min||'',e.ml||'',KIND[e.kind]||(e.type==='schlaf'?(e.kind==='nacht'?'Nacht':'Nickerchen'):''),DIA[e.diaper]||'',e.g||'',e.len?String(e.len).replace('.',','):'',e.head?String(e.head).replace('.',','):'',e.amount||'',e.wach||'',e.n||'',e.type==='temp'?String(e.c).replace('.',','):'',e.type==='medi'?[e.name,e.dose].filter(Boolean).join(' '):'',e.note||'',e.by||'']);
  });
  dl.save({filename:'trinkprotokoll-'+dayKey(Date.now())+'.csv',data:'﻿'+rows.map(function(r){return r.map(q).join(';');}).join('\r\n')})
    .then(function(){toast('Datei gespeichert');}).catch(function(er){if(er&&er.code!=='declined')toast('Die Datei konnte nicht gespeichert werden.');});
});

/* ---------- Anzeige und Navigation ---------- */
function renderHeader(){
  var a=ageText(),n=(settings.name||'').trim();
  $('#who').textContent=[n,a].filter(Boolean).join(' · ')||'Unser Baby';
  renderBabies();
}
function renderView(){
  renderHeader();
  if(view==='erfassen')renderToday();else if(view==='verlauf')renderHistory();else renderStats();
}
function route(){
  var hs=(location.hash||'').slice(1);
  view=hs==='verlauf'||hs==='statistik'?hs:'erfassen';
  document.querySelectorAll('[data-view]').forEach(function(s){s.hidden=s.getAttribute('data-view')!==view;});
  document.querySelectorAll('.nav a').forEach(function(a){if(a.getAttribute('data-go')===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  renderView();window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);
var rzT=null,lastW=0;
if(window.ResizeObserver){new ResizeObserver(function(){
  var w=$('.wrap').clientWidth;if(w===lastW)return;lastW=w;
  clearTimeout(rzT);rzT=setTimeout(function(){if(view==='statistik')renderStats();},120);}).observe($('.wrap'));}
var ticks=0;
setInterval(function(){
  ticks++;
  if(timer){renderBanner();updateTimerUi();}
  if(sleepTimer)renderSleepBanner();
  if(ticks%30===0&&view==='erfassen')renderToday();
},1000);

/* ---------- Daten ---------- */
window.addEventListener('trink-conn',function(e){
  if(e.detail&&e.detail.ok)delete notices.conn;
  else notices.conn='Der Server ist gerade nicht erreichbar. Neue Einträge lassen sich erst wieder speichern, wenn die Verbindung steht.';
  updateNotice();
});
/* ---------- Schlaf, Beikost, Archiv-Ansicht ---------- */
var sleepTimer=null;
try{sleepTimer=JSON.parse(localStorage.getItem('trinkprotokoll-schlaf')||'null');}catch(e){sleepTimer=null;}
function saveSleepTimer(){try{if(sleepTimer)localStorage.setItem('trinkprotokoll-schlaf',JSON.stringify(sleepTimer));else localStorage.removeItem('trinkprotokoll-schlaf');}catch(e){}}
function renderSleepBanner(){
  var b=$('#sleepBanner');if(!b)return;
  if(!sleepTimer){b.hidden=true;return;}
  var m=Math.max(0,Math.floor((Date.now()-sleepTimer.start)/6e4));
  b.hidden=false;b.textContent='';
  b.append('Schlaf läuft seit ',h('output',{text:fmtDur(m)}),' · zum Beenden tippen');
}
$('#sleepBanner').addEventListener('click',function(){openSheet('schlaf');});
function sleepKindFor(ts){var hr=new Date(ts).getHours();return hr>=18||hr<5?'nacht':'nap';}
function dtField(id,label,val){
  var inp=h('input',{id:id,type:'datetime-local',value:toLocalInput(val)});
  return h('div',{class:'field'},h('label',{for:id,text:label}),h('div',{class:'row2'},inp,h('button',{type:'button',class:'ghost',text:'Jetzt',onclick:function(){inp.value=toLocalInput(Date.now());}})));
}
function sleepSheet(box){
  var st=sleepTimer?sleepTimer.start:null,startDef=st||Date.now()-30*6e4;
  box.append(seg('skind','Art',[['nap','Nickerchen'],['nacht','Nachtschlaf']],sleepKindFor(startDef)));
  if(sleepTimer){
    box.append(h('p',{class:'hintl',text:'Der Timer läuft seit '+hhmm(sleepTimer.start)+' Uhr. Die Zeiten sind schon eingetragen, du kannst sie ändern.'}),
      h('button',{type:'button',class:'ghost',text:'Timer verwerfen',onclick:function(){sleepTimer=null;saveSleepTimer();renderSleepBanner();closeSheet();toast('Timer verworfen');}}));
  }else{
    box.append(h('button',{type:'button',class:'ghost',text:'Schläft jetzt: Timer starten',onclick:function(){sleepTimer={start:Date.now()};saveSleepTimer();closeSheet();renderSleepBanner();toast('Schlaf-Timer läuft. Zum Beenden oben antippen.');}}));
  }
  box.append(dtField('f-time','Eingeschlafen',startDef),dtField('f-end','Aufgewacht',Date.now()));
  var night=h('div',{id:'nightFields'},
    numField('f-wach','Davon wach (optional)',{min:0,max:600,val:'',start:20,inc:5,unit:'Min',chips:[10,20,30,45,60]}),
    numField('f-n','Wie oft wach (optional)',{min:0,max:30,val:'',start:1,inc:1,unit:'×'}));
  box.append(night,noteField());
  var sync=function(){night.hidden=document.querySelector('input[name=skind]:checked').value!=='nacht';};
  box.querySelectorAll('input[name=skind]').forEach(function(r){r.addEventListener('change',sync);});
  sync();
}
function beikostSheet(box){
  box.append(numField('f-bg','Menge (optional)',{min:5,max:600,val:'',start:120,inc:10,unit:'g',chips:[30,60,90,120,150,180]}),timeField(),noteField());
}
var anchor=null;
function refNow(){return anchor||Date.now();}
function setAnchor(){
  var B=window.TrinkBabies;anchor=null;delete notices.archiv;
  if(B){
    var cur=B.current(),b=B.list().filter(function(x){return x.id===cur;})[0];
    if(b&&b.last&&b.last<Date.now()-3*DAY){anchor=b.last;var d=new Date(b.last);notices.archiv='Dies ist ein älteres Baby. Statistik und Verlauf zeigen die letzten Tage bis zum letzten Eintrag am '+d.getDate()+'.'+(d.getMonth()+1)+'.'+d.getFullYear()+'.';}
  }
  updateNotice();
}
/* ---------- Gesundheit: Temperatur und Medikamente ---------- */
var WHERE={rektal:'rektal',ohr:'im Ohr',stirn:'an der Stirn',achsel:'unter der Achsel'};
function tempFlag(c){return c>=38?'Fieber':c>=37.5?'erhöht':c<36?'niedrig':'';}
function fmtC(c){return fmtDec(+c,1)+' °C';}
function babyDays(){if(!settings.birth)return null;var b=new Date(settings.birth+'T00:00:00');if(isNaN(b))return null;return Math.round((startOfDay(refNow())-b)/DAY);}
function lastMedi(name){var k=String(name||'').trim().toLowerCase();if(!k)return null;for(var i=0;i<events.length;i++){if(events[i].type==='medi'&&String(events[i].name||'').trim().toLowerCase()===k)return events[i];}return null;}
function whenText(ts){return (dayKey(ts)===dayKey(Date.now())?'heute':dLabel(new Date(ts)))+' um '+hhmm(ts)+' Uhr ('+ago(ts)+')';}
function tempSheet(box){
  var lt=lastOf('temp');
  var hint=h('p',{class:'hintl'});
  box.append(numField('f-c','Temperatur',{min:34,max:43,val:'',start:36.8,inc:0.1,unit:'°C',dec:true,chips:[36.5,37,37.5,38,38.5,39]}),
    seg('where','Gemessen',[['rektal','Rektal'],['ohr','Ohr'],['stirn','Stirn'],['achsel','Achsel']],lt&&WHERE[lt.where]?lt.where:'rektal'),hint,timeField(),noteField());
  var upd=function(){
    var fe=$('#f-c');if(!fe)return;var v=+fe.value,t='';
    if(fe.value!==''&&v>=38){
      var d=babyDays();
      t='Ab 38,0 °C gilt als Fieber. '+(d!=null&&d<90?'Bei Babys unter 3 Monaten bitte umgehend ärztlich abklären lassen.':'Bei Unsicherheit oder wenn es länger anhält, bitte die Kinderärztin oder den Kinderarzt anrufen.');
    }else if(fe.value!==''&&v>0&&v<36){t='Unter 36,0 °C ist ungewöhnlich niedrig. Bitte noch einmal messen, bei Unsicherheit ärztlichen Rat holen.';}
    hint.textContent=t;
  };
  var fc=$('#f-c');fc.addEventListener('input',upd);fc.closest('.field').addEventListener('click',function(){setTimeout(upd,0);});
}
function mediNames(){var seen={},out=[];events.forEach(function(e){if(e.type!=='medi')return;var k=String(e.name||'').trim().toLowerCase();if(k&&!seen[k]){seen[k]=1;out.push(e);}});return out;}
function mediSheet(box){
  var names=mediNames().slice(0,6),hint=h('p',{class:'hintl'});
  var dl=h('datalist',{id:'mediList'});
  ['Paracetamol','Ibuprofen','Sab simplex','BiGaia','Kochsalz-Nasentropfen'].concat(names.map(function(e){return e.name;})).forEach(function(n){dl.append(h('option',{value:n}));});
  var nameIn=h('input',{id:'f-mname',type:'text',maxlength:'60',list:'mediList',autocomplete:'off',placeholder:'z. B. Paracetamol-Zäpfchen'});
  var doseIn=h('input',{id:'f-dose',type:'text',maxlength:'40',placeholder:'z. B. 2,5 ml oder 1 Zäpfchen'});
  box.append(h('div',{class:'field'},h('label',{for:'f-mname',text:'Medikament'}),nameIn),dl);
  if(names.length){
    var chips=h('div',{class:'chips'});
    names.forEach(function(e){chips.append(h('button',{type:'button',class:'chip',text:e.name,onclick:function(){nameIn.value=e.name;doseIn.value=e.dose||'';upd();}}));});
    box.append(chips);
  }
  box.append(h('div',{class:'field'},h('label',{for:'f-dose',text:'Menge (optional)'}),doseIn),hint,timeField(),noteField(),
    h('p',{class:'hintl',text:'Die Menge immer nach Packungsbeilage oder Anweisung der Kinderärztin oder des Kinderarztes wählen.'}));
  var upd=function(){var l=lastMedi(nameIn.value);hint.textContent=l?'Zuletzt gegeben: '+whenText(l.ts)+(l.dose?', '+l.dose:'')+'.':'';};
  nameIn.addEventListener('input',upd);
}
function healthEvents(days){
  var a=days[0].date.getTime(),z=startOfDay(days[days.length-1].date.getTime()).getTime()+DAY;
  var t=[],m=[];
  events.forEach(function(e){if(e.ts<a||e.ts>=z)return;if(e.type==='temp'&&+e.c>0)t.push(e);else if(e.type==='medi')m.push(e);});
  t.sort(function(x,y){return x.ts-y.ts;});m.sort(function(x,y){return x.ts-y.ts;});
  return {temps:t,medis:m,a:a,z:z};
}
function tempChart(host,days,he){
  var cs=he.temps.map(function(e){return +e.c;});
  var lo=Math.min(36,Math.floor(Math.min.apply(null,cs.concat([36])))),hi=Math.max(39,Math.ceil(Math.max.apply(null,cs.concat([39]))));
  var W=Math.max(260,host.clientWidth||320),H=he.medis.length?250:230,m={l:40,r:10,t:14,b:he.medis.length?58:40},pw=W-m.l-m.r,ph=H-m.t-m.b;
  var X=function(ts){return m.l+((ts-he.a)/(he.z-he.a))*pw;},Y=function(v){return m.t+ph-((v-lo)/(hi-lo))*ph;};
  var s='<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="Temperaturverlauf mit Medikamentengaben">';
  for(var g=lo;g<=hi+1e-9;g+=1){s+='<line class="'+(g===lo?'ax':'gr')+'" x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+Y(g)+'" y2="'+Y(g)+'"/><text x="'+(m.l-6)+'" y="'+(Y(g)+4)+'" text-anchor="end">'+g+'</text>';}
  s+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+Y(38)+'" y2="'+Y(38)+'" stroke="var(--c-fieber)" stroke-width="1.5" stroke-dasharray="5 4"/><text x="'+(m.l+4)+'" y="'+(Y(38)-4)+'" text-anchor="start" fill="var(--c-fieber)">38,0</text>';
  var every=Math.max(1,Math.ceil(days.length*36/pw));
  days.forEach(function(d,i){if(i%every)return;var cx=X(d.date.getTime()+DAY/2);s+='<text x="'+cx+'" y="'+(m.t+ph+15)+'" text-anchor="middle">'+(days.length<=10?WD[d.date.getDay()]+' ':'')+d.date.getDate()+'.</text>';});
  if(he.temps.length>1)s+='<polyline fill="none" stroke="var(--c-temp)" stroke-width="1.5" stroke-opacity=".5" stroke-linejoin="round" points="'+he.temps.map(function(e){return X(e.ts)+','+Y(+e.c);}).join(' ')+'"/>';
  he.temps.forEach(function(e){
    var f=tempFlag(+e.c),tip=[fmtC(e.c)+(f?' · '+f:''),dLabel(new Date(e.ts))+', '+hhmm(e.ts)+' Uhr'+(WHERE[e.where]?' · '+WHERE[e.where]:'')];
    s+='<circle cx="'+X(e.ts)+'" cy="'+Y(+e.c)+'" r="4.5" fill="'+(+e.c>=38?'var(--c-fieber)':'var(--c-temp)')+'" stroke="var(--surface)" stroke-width="1.5"/><circle cx="'+X(e.ts)+'" cy="'+Y(+e.c)+'" r="12" fill="transparent" data-tip="'+esc(tip.join('|'))+'"/>';
  });
  he.medis.forEach(function(e){
    var cx=X(e.ts),cy=m.t+ph+30,tip=[e.name+(e.dose?' · '+e.dose:''),dLabel(new Date(e.ts))+', '+hhmm(e.ts)+' Uhr'];
    s+='<path d="M'+(cx-5)+','+(cy+5)+' L'+(cx+5)+','+(cy+5)+' L'+cx+','+(cy-5)+' Z" fill="var(--c-medi)"/><rect x="'+(cx-10)+'" y="'+(cy-10)+'" width="20" height="20" fill="transparent" data-tip="'+esc(tip.join('|'))+'"/>';
  });
  host.innerHTML=s+'</svg>';
}
function renderHealth(days){
  var card=$('#healthCard');if(!card)return;
  var he=healthEvents(days);
  if(!he.temps.length&&!he.medis.length){card.hidden=true;return;}
  card.hidden=false;
  var cs=he.temps.map(function(e){return +e.c;}),parts=[];
  if(cs.length){parts.push(cs.length+(cs.length===1?' Messung':' Messungen')+', höchster Wert '+fmtC(Math.max.apply(null,cs)));var fe=cs.filter(function(c){return c>=38;}).length;if(fe)parts.push(fe+'× ab 38,0 °C');}
  if(he.medis.length)parts.push(he.medis.length+(he.medis.length===1?' Medikamentengabe':' Medikamentengaben'));
  $('#sub-health').textContent=parts.join(' · ');
  legend('#lg-health',[{label:'Temperatur',color:'var(--c-temp)'},{label:'ab 38,0 °C',color:'var(--c-fieber)'}].concat(he.medis.length?[{label:'Medikament',color:'var(--c-medi)',shape:'tick'}]:[]));
  var host=$('#ch-health');host.textContent='';
  if(he.temps.length)tempChart(host,days,he);
  var ml=$('#medList');ml.textContent='';
  var groups={},order=[];
  he.medis.forEach(function(e){var k=e.name.trim().toLowerCase();if(!groups[k]){groups[k]={name:e.name,list:[]};order.push(k);}groups[k].list.push(e);});
  order.forEach(function(k){
    var g=groups[k],l=g.list[g.list.length-1];
    ml.append(h('li',null,h('b',{text:g.name}),' · '+g.list.length+'×, zuletzt '+dLabel(new Date(l.ts))+', '+hhmm(l.ts)+' Uhr'+(l.dose?' · '+l.dose:'')));
  });
  ml.hidden=!order.length;
}
/* ---------- Einträge bearbeiten ---------- */
var editing=null;
function editEvent(e){
  if(!canWrite)return;
  var t=e.type==='gewicht'?'wachstum':e.type;
  if(!TYPES[t])return;
  openSheet(t,e);
}
function prefillEdit(e){
  var box=$('#sheetFields');
  var val=function(id,v){var el=document.getElementById(id);if(el&&v!=null&&v!=='')el.value=v;};
  var pick=function(name,v){var r=document.getElementById(name+'-'+v);if(r){r.checked=true;r.dispatchEvent(new Event('change',{bubbles:true}));}};
  var tm=box.querySelector('.timer');if(tm)tm.remove();
  val('f-time',toLocalInput(e.ts));val('f-note',e.note||'');
  switch(e.type){
    case 'stillen':pick('side',e.side);val('f-min',e.min);break;
    case 'flasche':val('f-ml',e.ml);pick('kind',e.kind);break;
    case 'windel':pick('diaper',e.diaper);break;
    case 'gewicht':case 'wachstum':val('f-g',e.g);val('f-len',e.len);val('f-head',e.head);break;
    case 'spucken':pick('amount',e.amount);break;
    case 'beikost':val('f-bg',e.g);break;
    case 'temp':val('f-c',e.c);pick('where',e.where);var fc=document.getElementById('f-c');if(fc)fc.dispatchEvent(new Event('input'));break;
    case 'medi':val('f-mname',e.name);val('f-dose',e.dose);var mn=document.getElementById('f-mname');if(mn)mn.dispatchEvent(new Event('input'));break;
    case 'schlaf':
      Array.prototype.slice.call(box.children).forEach(function(c){
        if(c.tagName==='BUTTON'&&c.classList.contains('ghost'))c.remove();
        else if(c.tagName==='P'&&/Timer/.test(c.textContent))c.remove();
      });
      pick('skind',e.kind==='nacht'?'nacht':'nap');
      val('f-end',toLocalInput(e.ts+(+e.min||0)*6e4));val('f-wach',e.wach);val('f-n',e.n);
      break;
  }
}
function connect(){
  if(!window.claude||!window.claude.use){notices.nodb='Speichern ist in dieser Ansicht nicht möglich. Öffne die Seite in Claude.';updateNotice();return;}
  Promise.all([window.claude.use('db'),window.claude.use('user'),window.claude.use('downloads')]).then(function(r){
    db=r[0];dl=r[2];
    if(!db){notices.nodb='Speichern ist in dieser Ansicht nicht möglich. Öffne die Seite in Claude und melde dich an.';canWrite=false;buildActions();updateNotice();renderView();return;}
    var u=r[1];
    var pc=u&&u.can?u.can('data.write'):Promise.resolve(null);
    return pc.then(function(ok){
      if(ok===false){canWrite=false;$('#btnSettings').hidden=true;notices.ro='Dein Zugang ist nur zum Ansehen. Einträge anlegen können Mitglieder und Admins.';buildActions();updateNotice();}
      var fresh=false;
      var staleT=setTimeout(function(){if(!fresh){notices.stale='Die Daten lassen sich gerade nicht erreichen. Angezeigt wird der zuletzt bekannte Stand.';updateNotice();}},10000);
      var onErr=function(){clearTimeout(staleT);notices.err='Die Daten konnten nicht geladen werden. Bitte die Seite neu öffnen.';updateNotice();};
      var okSnap=function(s){if(!s.metadata.fromCache){fresh=true;clearTimeout(staleT);if(notices.stale||notices.err){delete notices.stale;delete notices.err;updateNotice();}}};
      setAnchor();
      var cutoff=refNow()-31*DAY;
      db.collection('events').where('ts','>=',cutoff).orderBy('ts','desc').limit(1000).onSnapshot(function(s){
        okSnap(s);
        events=s.docs.map(function(d){var o=d.data();o.id=d.id;return o;}).sort(function(a,b){return b.ts-a.ts;});
        renderView();
      },onErr);
      db.collection('events').where('type','in',['gewicht','wachstum']).orderBy('ts','asc').limit(500).onSnapshot(function(s){
        growth=s.docs.map(function(d){var o=d.data();o.id=d.id;return o;});
        if(view==='statistik')renderStats();
      },onErr);
      db.doc('settings/baby').onSnapshot(function(s){settings=s.exists?s.data():{};renderView();if(window.TrinkBabies)window.TrinkBabies.refresh().then(renderBabies);},onErr);
    });
  }).catch(function(){notices.err='Die Verbindung zum Speicher ist fehlgeschlagen.';updateNotice();});
}

buildActions();
route();
connect();
})();
