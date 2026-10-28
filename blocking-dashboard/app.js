/* Blocking Observatory: self-contained static explorer; no external requests. */
(async function(){
  'use strict';
  const C=window.BlockingCore,$=id=>document.getElementById(id);
  const monthNames=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const state={method:'ppa',period:'daily',region:null,hemisphere:'both',layer:'anomaly',reference:[1980,2014],season:'DJF',month:10,year:2026,date:'',playing:null,climateSlice:'all'};
  const seriesCache=new Map(),gridCache=new Map();
  let data,ncell,allYears,dateIndex,fieldIndex;
  const dateLabel=d=>new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
  const pct=v=>v===null||!Number.isFinite(v)?'—':v.toFixed(1);
  const showToast=message=>{ $('toast').textContent=message;$('toast').hidden=false;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>$('toast').hidden=true,3500); };
  function base64Bytes(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}
  async function unpack(s){
    const stream=new Blob([base64Bytes(s)]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }
  function decodeData(raw){
    for(const key of Object.keys(raw.masks))raw.masks[key]=base64Bytes(raw.masks[key]);
    if(raw.fields)for(const key of ['z500','anomaly']){
      const b=base64Bytes(raw.fields[key]);raw.fields[key]=new Int16Array(b.buffer,b.byteOffset,b.byteLength/2);
      if(raw.fields.encoding==='delta-time-i16'){
        const stride=raw.grid.latitudes.length*raw.grid.longitudes.length,arr=raw.fields[key];
        for(let i=stride;i<arr.length;i++)arr[i]+=arr[i-stride];
      }
    }
    return raw;
  }
  function currentCells(region=state.region,hemisphere=state.hemisphere){return C.cellsFor(data.grid,region,hemisphere);}
  function getSeries(region=state.region,hemisphere=state.hemisphere){
    const key=state.method+'|'+(region?region.id:'global')+'|'+hemisphere;
    if(!seriesCache.has(key))seriesCache.set(key,C.areaSeries(data,state.method,currentCells(region,hemisphere)));
    return seriesCache.get(key);
  }
  function options(){return{...state};}
  function indices(){return C.selectDates(data.dates,options());}
  function setDate(d){
    if(!dateIndex.has(d))return;
    state.date=d;state.year=+d.slice(0,4);state.month=+d.slice(5,7);
  }
  function selectRegion(region){
    state.region=region;state.hemisphere=region?region.hemisphere:'both';
    update();
  }
  function makeOptions(select,values,labels){
    select.replaceChildren(...values.map((value,i)=>{const option=document.createElement('option');option.value=value;option.textContent=labels?labels[i]:value;return option;}));
  }
  function initControls(){
    const first=data.dates[0],last=data.dates.at(-1);
    $('date').min=first;$('date').max=last;
    makeOptions($('selected-year'),[...allYears].reverse());
    makeOptions($('selected-month'),Array.from({length:12},(_,i)=>i+1),monthNames);
    const completeYears=allYears.filter(y=>data.dates.includes(`${y}-01-01`)&&data.dates.includes(`${y}-12-31`));
    makeOptions($('reference-start'),completeYears);makeOptions($('reference-end'),completeYears);
    $('reference-start').value=state.reference[0];$('reference-end').value=state.reference[1];
    if(!completeYears.length){makeOptions($('reference-start'),['pending'],['Pending']);makeOptions($('reference-end'),['pending'],['Pending']);}
    const referenceAvailable=data.meta.reference_available!==false&&completeYears.length>0;
    for(const id of ['reference-start','reference-end','apply-reference'])$(id).disabled=!referenceAvailable;
    document.querySelector('[data-period="climatology"]').disabled=!referenceAvailable;
    const methods=data.meta.available_methods||['ppa','tr'];
    document.querySelectorAll('[data-method]').forEach(b=>{b.disabled=!methods.includes(b.dataset.method);if(b.disabled)b.title='Requires the historical Z500 reference, which is not loaded.';});
    const slice=document.createElement('select');slice.id='climate-slice';slice.setAttribute('aria-label','Climatology season or month');
    makeOptions(slice,['all','DJF','MAM','JJA','SON',...Array.from({length:12},(_,i)=>String(i+1))],['All year','DJF','MAM','JJA','SON',...monthNames]);
    $('aggregate-controls').append(slice);
    for(const region of data.regions){
      const b=document.createElement('button');b.className='region-button';b.dataset.region=region.id;
      b.innerHTML='<span class="region-name"></span><span class="region-value"><span class="number"></span><i class="activity-dot"></i></span>';
      b.querySelector('.region-name').textContent=region.name;
      b.addEventListener('click',()=>selectRegion(region));$(region.hemisphere+'-regions').append(b);
    }
    document.querySelectorAll('[data-method]').forEach(b=>b.addEventListener('click',()=>{state.method=b.dataset.method;update();}));
    document.querySelectorAll('[data-period]').forEach(b=>b.addEventListener('click',()=>{stopPlay();state.period=b.dataset.period;update();}));
    document.querySelectorAll('[data-open-methods]').forEach(b=>b.addEventListener('click',()=>$('methods-dialog').showModal()));
    $('close-methods').addEventListener('click',()=>$('methods-dialog').close());
    $('methods-dialog').addEventListener('click',event=>{if(event.target===$('methods-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
    $('global-region').addEventListener('click',()=>selectRegion(null));$('reset-map').addEventListener('click',()=>selectRegion(null));
    $('hemisphere').addEventListener('change',()=>{state.hemisphere=$('hemisphere').value;state.region=null;update();});
    $('layer').addEventListener('change',()=>{state.layer=$('layer').value;update();});
    $('date').addEventListener('change',()=>{setDate($('date').value);update();});
    $('selected-year').addEventListener('change',()=>{
      const year=+$('selected-year').value;
      let d=year+state.date.slice(4);
      if(!dateIndex.has(d))d=data.dates.filter(v=>v.startsWith(String(year))).at(-1);
      setDate(d);update();
    });
    $('selected-month').addEventListener('change',()=>{state.month=+$('selected-month').value;update();});
    $('selected-season').addEventListener('change',()=>{state.season=$('selected-season').value;update();});
    slice.addEventListener('change',()=>{state.climateSlice=slice.value;update();});
    $('timeline').addEventListener('input',()=>{const days=data.dates.filter(d=>+d.slice(0,4)===state.year);setDate(days[+$('timeline').value]);update();});
    $('previous-day').addEventListener('click',()=>stepDay(-1));$('next-day').addEventListener('click',()=>stepDay(1));
    $('play').addEventListener('click',()=>{
      if(state.playing){stopPlay();return;}
      state.period='daily';$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','Pause daily animation');
      state.playing=setInterval(()=>{const days=data.dates.filter(d=>+d.slice(0,4)===state.year);const i=days.indexOf(state.date);setDate(days[(i+1)%days.length]);update();},600);
      update();
    });
    $('apply-reference').addEventListener('click',()=>{
      const start=+$('reference-start').value,end=+$('reference-end').value;
      if(start>end){$('reference-error').textContent='The start year must be no later than the end year.';$('reference-error').hidden=false;return;}
      $('reference-error').hidden=true;state.reference=[start,end];gridCache.clear();update();showToast(`Blocking climatology updated to ${start}–${end}.`);
    });
    $('export-csv').addEventListener('click',exportCSV);$('export-map').addEventListener('click',exportMap);
    window.addEventListener('beforeunload',stopPlay);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPlay();});
  }
  function stopPlay(){if(state.playing)clearInterval(state.playing);state.playing=null;$('play').textContent='▶';$('play').setAttribute('aria-label','Play daily animation');}
  function stepDay(delta){const i=dateIndex.get(state.date),next=i+delta;if(next>=0&&next<data.dates.length){setDate(data.dates[next]);update();}}
  function syncControls(){
    $('date').value=state.date;$('hemisphere').value=state.hemisphere;$('selected-year').value=state.year;$('selected-month').value=state.month;
    $('selected-season').value=state.season;
    $('climate-slice').value=state.climateSlice;
    const daily=state.period==='daily',climate=state.period==='climatology';
    $('date').hidden=!daily;$('aggregate-controls').hidden=daily;$('selected-year').hidden=climate;
    $('selected-month').hidden=state.period!=='monthly';$('selected-season').hidden=state.period!=='seasonal';$('climate-slice').hidden=!climate;
    $('timeline').hidden=!daily;$('play').disabled=!daily;$('previous-day').disabled=!daily||dateIndex.get(state.date)===0;$('next-day').disabled=!daily||dateIndex.get(state.date)===data.dates.length-1;
    const days=data.dates.filter(d=>+d.slice(0,4)===state.year);$('timeline').max=Math.max(0,days.length-1);$('timeline').value=days.indexOf(state.date);
    const hasField=data.fields&&fieldIndex.has(state.date);
    const fieldLayers=data.meta.available_fields||['anomaly','z500'];
    if(state.layer!=='blocked'&&!fieldLayers.includes(state.layer))state.layer=fieldLayers[0]||'blocked';
    for(const opt of $('layer').options)if(opt.value!=='blocked')opt.disabled=!daily||!hasField||!fieldLayers.includes(opt.value);
    if(!daily||!hasField)$('layer').value='blocked';else $('layer').value=state.layer;
    document.querySelectorAll('[data-method]').forEach(b=>{const yes=b.dataset.method===state.method;b.classList.toggle('selected',yes);b.setAttribute('aria-pressed',yes);});
    document.querySelectorAll('[data-period]').forEach(b=>{const yes=b.dataset.period===state.period;b.classList.toggle('selected',yes);b.setAttribute('aria-pressed',yes);});
    $('global-region').classList.toggle('selected',!state.region);$('reset-map').hidden=!state.region&&state.hemisphere==='both';
    const index=dateIndex.get(state.date);
    document.querySelectorAll('[data-region]').forEach(b=>{
      const region=data.regions.find(r=>r.id===b.dataset.region),series=getSeries(region,region.hemisphere),v=series[index];
      b.classList.toggle('selected',state.region?.id===region.id);b.setAttribute('aria-pressed',state.region?.id===region.id);
      b.querySelector('.number').textContent=pct(v)+'%';b.querySelector('.activity-dot').classList.toggle('on',v!==null&&v>0);
    });
    $('method-caption').textContent=state.method==='ppa'?'PPA · ≥100 m anomaly · ≥5 consecutive days':'TR · three gradient tests · ≥4 consecutive days';
    $('reference-note').textContent=data.meta.reference_available===false?'Historical reference not loaded. PPA and climatology will become available when it is added. NH extension awaits author validation.':`The PPA height-anomaly reference remains ${data.meta.anomaly_reference.join('–')}. Changing this comparison does not redefine detection. NH extension awaits author validation.`;
  }
  function periodTitle(){
    if(state.period==='daily')return dateLabel(state.date)+' · 00:00 UTC';
    if(state.period==='monthly')return monthNames[state.month-1]+' '+state.year;
    if(state.period==='seasonal')return state.season+' '+state.year+(state.season==='DJF'?' · season year follows January':'');
    if(state.period==='annual')return String(state.year);
    return state.reference.join('–')+' · '+(state.climateSlice==='all'?'all year':monthNames[+state.climateSlice-1]||state.climateSlice);
  }
  function mapValues(){
    const daily=state.period==='daily',layer=$('layer').value,day=dateIndex.get(state.date);
    if(daily&&layer!=='blocked'&&fieldIndex.has(state.date)){
      const start=fieldIndex.get(state.date)*ncell,arr=data.fields[layer];
      return Float32Array.from(arr.subarray(start,start+ncell),v=>v===-32768?NaN:v);
    }
    const ix=indices(),key=state.method+'|'+state.period+'|'+ix[0]+'|'+ix.at(-1)+'|'+ix.length+'|'+state.climateSlice;
    if(!gridCache.has(key))gridCache.set(key,C.aggregateGrid(data,state.method,ix));
    return gridCache.get(key);
  }
  const colors={anomaly:['#557b9c','#8badbf','#c6d9dc','#e8ede3','#e5dfaf','#d6b36a','#c58343','#a4562f','#7b382f'],frequency:['#edf1df','#d5e0b2','#adca8c','#7fa56c','#4d805c','#28694e','#16503f'],z500:['#7e8cae','#9eafca','#adcfcb','#cbe1be','#dfe5b2','#e6d18d','#dca263','#be7151']};
  function palette(){const layer=$('layer').value;if(layer==='anomaly')return{thresholds:[-300,-200,-100,-25,25,100,150,200,300],colors:colors.anomaly,label:'Z500 anomaly (m)'};if(layer==='z500')return{thresholds:[4500,4800,5000,5200,5400,5600,5800,6000],colors:colors.z500,label:'Z500 height (m)'};return{thresholds:[1,5,10,20,40,60,80],colors:colors.frequency,label:state.period==='daily'?'Confirmed blocked area':'Blocking frequency (%)'};}
  function renderMap(){
    const svg=d3.select('#world-map');svg.selectAll('*').remove();
    const width=1040,height=440,pad={l:43,r:19,t:15,b:27};
    const region=state.region,centerLon=region?Math.round(region.center[0]/data.meta.grid_degrees)*data.meta.grid_degrees:0;
    const centerLat=region?region.center[1]:(state.hemisphere==='nh'?52.5:state.hemisphere==='sh'?-52.5:0);
    const scale=region?Math.min((width-pad.l-pad.r)/(110*Math.PI/180),(height-pad.t-pad.b)/(55*Math.PI/180)):(width-pad.l-pad.r)/(360*Math.PI/180);
    const ppd=scale*Math.PI/180,midX=(width+pad.l-pad.r)/2,midY=(height+pad.t-pad.b)/2;
    const projection=d3.geoEquirectangular().rotate([-centerLon,0]).center([0,centerLat]).scale(scale).translate([midX,midY]).clipExtent([[pad.l,pad.t],[width-pad.r,height-pad.b]]);
    const geoPath=d3.geoPath(projection),x=lon=>midX+(lon-centerLon)*ppd,y=lat=>midY-(lat-centerLat)*ppd;
    const clip=svg.append('defs').append('clipPath').attr('id','map-clip');clip.append('rect').attr('x',pad.l).attr('y',pad.t).attr('width',width-pad.l-pad.r).attr('height',height-pad.t-pad.b);
    const content=svg.append('g').attr('clip-path','url(#map-clip)');
    content.append('rect').attr('x',pad.l).attr('y',pad.t).attr('width',width-pad.l-pad.r).attr('height',height-pad.t-pad.b).attr('fill','#f5f8f5');
    content.append('path').datum(window.BLOCKING_LAND).attr('d',geoPath).attr('fill','#e7ede3').attr('stroke','none');
    const values=mapValues(),nx=data.grid.longitudes.length,ny=data.grid.latitudes.length,step=data.meta.grid_degrees;
    const startLon=centerLon-180,sourceIndices=Array.from({length:nx+1},(_,i)=>{
      const lon=((startLon+i*step+180)%360+360)%360-180;
      return Math.round((lon-data.grid.longitudes[0])/step)%nx;
    });
    const shifted=new Float32Array((nx+1)*ny);
    for(let j=0;j<ny;j++)for(let i=0;i<=nx;i++){
      const value=values[j*nx+sourceIndices[i]],lat=data.grid.latitudes[j];
      const inBand=Math.abs(lat)>=30&&Math.abs(lat)<=75&&(state.hemisphere==='both'||(state.hemisphere==='nh'?lat>0:lat<0));
      shifted[j*(nx+1)+i]=inBand&&Number.isFinite(value)?value:-99999;
    }
    const p=palette(),contourPath=d3.geoPath(),transform=`translate(${x(startLon-step/2)},${y(data.grid.latitudes[0]+step/2)}) scale(${ppd*step},${ppd*step})`;
    const contourGroup=content.append('g').attr('transform',transform);
    const contourData=d3.contours().size([nx+1,ny]).thresholds(p.thresholds)(shifted);
    contourGroup.selectAll('path.field').data(contourData).join('path').attr('class','field').attr('d',contourPath).attr('fill',(_,i)=>p.colors[i]).attr('opacity',.85).attr('stroke','none');
    // Always outline confirmed gridpoint masks, independently of the colour layer.
    if(state.period==='daily'){
      for(const [name,stroke,dash] of [[state.method,'#3c573c',null],['pending_'+state.method,'#9b6845','4 3']]){
        const binary=new Float32Array((nx+1)*ny),day=dateIndex.get(state.date);
        for(let j=0;j<ny;j++)for(let i=0;i<=nx;i++){
          const lat=data.grid.latitudes[j],band=state.hemisphere==='both'||(state.hemisphere==='nh'?lat>0:lat<0);
          binary[j*(nx+1)+i]=band?C.bit(data.masks[name],day*ncell+j*nx+sourceIndices[i]):0;
        }
        contourGroup.selectAll('path.outline-'+name).data(d3.contours().size([nx+1,ny]).thresholds([.5])(binary)).join('path').attr('d',contourPath).attr('fill','none').attr('stroke',stroke).attr('stroke-width',1.35/(ppd*step)).attr('stroke-dasharray',dash?dash.split(' ').map(v=>+v/(ppd*step)).join(' '):null);
      }
    }
    // Mask interpolation beyond the scientifically requested latitude domain.
    for(const [north,south] of [[90,75],[30,-30],[-75,-90]]){
      content.append('rect').attr('x',pad.l).attr('y',y(north)).attr('width',width-pad.l-pad.r).attr('height',y(south)-y(north)).attr('fill','#f5f8f5').attr('opacity',north===30?.9:1);
    }
    content.append('path').datum(window.BLOCKING_LAND).attr('d',geoPath).attr('fill','none').attr('stroke','#96a68c').attr('stroke-width',.65);
    content.append('path').datum(d3.geoGraticule().step([30,15])()).attr('d',geoPath).attr('class','map-gridline');
    for(const lat of [-75,-60,-45,-30,0,30,45,60,75]){
      const py=y(lat);if(py<pad.t||py>height-pad.b)continue;
      svg.append('text').attr('x',pad.l-8).attr('y',py+3).attr('text-anchor','end').attr('class','map-label').text(lat===0?'0°':Math.abs(lat)+'°'+(lat>0?'N':'S'));
    }
    for(let lon=-180;lon<=180;lon+=60){const px=x(lon+centerLon);if(px<pad.l||px>width-pad.r)continue;const normalized=((lon+centerLon+180)%360+360)%360-180;svg.append('text').attr('x',px).attr('y',height-8).attr('text-anchor','middle').attr('class','map-label').text(normalized===0?'0°':Math.abs(normalized)+'°'+(normalized>0?'E':'W'));}
    if(!region&&state.hemisphere==='both')content.append('text').attr('x',midX).attr('y',y(0)+3).attr('text-anchor','middle').attr('fill','#9daa91').attr('font-size',9).attr('letter-spacing',3).text('MID-LATITUDE BLOCKING · 30°–75°');
    for(const r of data.regions){
      if(state.hemisphere!=='both'&&state.hemisphere!==r.hemisphere)continue;
      if(region&&region.id!==r.id)continue;
      let [west,south,east,north]=r.bounds;
      if(east<west)east+=360;
      const cx=(west+east)/2,shift=Math.round((centerLon-cx)/360)*360;west+=shift;east+=shift;
      const g=content.append('g').attr('class','map-region').attr('role','button').attr('tabindex',0).attr('aria-label',`Explore ${r.name}`).on('click',()=>selectRegion(r)).on('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectRegion(r);}});
      const copies=region?[0]:[-360,0,360];
      for(const offset of copies){
        const rx=x(west+offset),rw=(east-west)*ppd;if(rx+rw<pad.l||rx>width-pad.r)continue;
        g.append('rect').attr('x',rx).attr('y',y(north)).attr('width',rw).attr('height',(north-south)*ppd).attr('rx',2).attr('fill',region?'#e2ecd615':'transparent').attr('stroke',region?'#2d654e':'#7b9670').attr('stroke-width',region?1.3:.8).attr('stroke-dasharray',region?null:'3 3');
        if(!region)g.append('text').attr('x',rx+rw/2).attr('y',y((north+south)/2)+4).attr('text-anchor','middle').attr('font-size',r.name.length>15?8:9).text(r.name);
      }
      g.append('title').text('Click to explore '+r.name);
    }
    content.append('rect').attr('x',pad.l).attr('y',pad.t).attr('width',width-pad.l-pad.r).attr('height',height-pad.t-pad.b).attr('fill','none').attr('stroke','#dce4d6').attr('stroke-width',.75);
    svg.on('pointermove',event=>{
      if(event.target.closest?.('.map-region')){$('map-tooltip').hidden=true;return;}
      const [mx,my]=d3.pointer(event),geo=projection.invert([mx,my]);if(!geo)return;
      const lon=((geo[0]+180)%360+360)%360-180,lat=geo[1],j=Math.round((data.grid.latitudes[0]-lat)/step),i=Math.round((lon-data.grid.longitudes[0])/step)%nx;
      if(j<0||j>=ny||i<0||Math.abs(lat)<30||Math.abs(lat)>75){$('map-tooltip').hidden=true;return;}
      const v=values[j*nx+i],units=$('layer').value==='blocked'?'%':' m';
      const tip=$('map-tooltip');tip.textContent=`${Math.abs(lat).toFixed(1)}°${lat>=0?'N':'S'}, ${Math.abs(lon).toFixed(1)}°${lon>=0?'E':'W'} · ${Number.isFinite(v)?v.toFixed(1)+units:'No data'}`;
      const wrap=$('world-map').getBoundingClientRect();tip.style.left=Math.min(event.clientX-wrap.left+10,wrap.width-190)+'px';tip.style.top=(event.clientY-wrap.top+13)+'px';tip.hidden=false;
    }).on('pointerleave',()=>$('map-tooltip').hidden=true);
    $('map-title').textContent=$('layer').value==='anomaly'?'Z500 anomaly':$('layer').value==='z500'?'Geopotential height at 500 hPa':state.period==='daily'?'Confirmed blocking':'Blocking frequency';
    const ix=indices(),expected=C.expectedDays(options()),regionalSeries=getSeries(),observed=ix.filter(i=>regionalSeries[i]!==null).length,incomplete=observed<expected;
    $('map-subtitle').textContent=`${periodTitle()} · ${state.method.toUpperCase()}${incomplete?' · incomplete period ('+observed+'/'+expected+' valid days)':''}`;
    $('map-watermark').textContent=data.meta.source==='synthetic'?'SYNTHETIC DEMONSTRATION':'ERA5 / ERA5T · 00:00 UTC';
    renderLegend(p);
  }
  function renderLegend(p){
    const div=$('legend');div.replaceChildren();const label=document.createElement('span');label.className='legend-label';label.textContent=p.label;div.append(label);
    const ramp=document.createElement('div');ramp.className='legend-ramp';
    p.colors.forEach((c,i)=>{const stop=document.createElement('div');stop.className='legend-stop';stop.style.background=c;const text=document.createElement('span');text.textContent=p.thresholds[i];stop.append(text);ramp.append(stop);});div.append(ramp);
  }
  function renderStatistics(){
    const series=getSeries(),yearIndices=data.dates.flatMap((d,i)=>+d.slice(0,4)===state.year?[i]:[]);
    const refIndices=C.selectDates(data.dates,{period:'climatology',reference:state.reference}),reference=C.mean(refIndices.map(i=>series[i]));
    const daily=state.period==='daily',statIndices=daily?yearIndices:indices(),periodValues=statIndices.map(i=>series[i]);
    const current=daily?series[dateIndex.get(state.date)]:C.mean(periodValues),nonNull=periodValues.filter(v=>v!==null),equivalent=nonNull.reduce((a,b)=>a+b/100,0),activeDays=nonNull.filter(v=>v>0).length;
    const statPeriod=daily?String(state.year):periodTitle();
    const globalName=state.hemisphere==='nh'?'Northern mid-latitudes':state.hemisphere==='sh'?'Southern mid-latitudes':'Global mid-latitudes';
    $('stats-title').textContent=state.region?state.region.name:globalName;
    const bounds=state.region?state.region.bounds:null;
    $('stats-subtitle').textContent=state.region?`${state.region.hemisphere==='nh'?'Northern':'Southern'} Hemisphere · ${Math.min(Math.abs(bounds[1]),Math.abs(bounds[3]))}°–${Math.max(Math.abs(bounds[1]),Math.abs(bounds[3]))}°${state.region.hemisphere==='nh'?'N':'S'} · cosine-latitude weighting.`:`Area-weighted statistics across 30°–75° ${state.hemisphere==='both'?'in both hemispheres':state.hemisphere==='nh'?'N':'S'}.`;
    const kpis=[[daily?'Blocked area':'Mean blocked area',pct(current),'%',(daily?dateLabel(state.date):statPeriod)+' · confirmed only'],['Regional blocked days',nonNull.length?String(activeDays):'—','days',statPeriod+' · ≥1 grid cell blocked · '+nonNull.length+' valid days'],['Equivalent blocked days',nonNull.length?equivalent.toFixed(equivalent>0&&equivalent<1?3:1):'—','days',statPeriod+' · sum of daily blocked area fractions'],['Reference frequency',pct(reference),'%',data.meta.reference_available===false?'Historical reference not loaded':state.reference.join('–')+' · mean daily blocked area']];
    $('kpis').replaceChildren(...kpis.map((k,i)=>{const div=document.createElement('div');div.className='kpi';const label=document.createElement('div');label.className='kpi-label';label.textContent=k[0];const value=document.createElement('div');value.className='kpi-value';value.textContent=k[1];const small=document.createElement('small');small.textContent=k[2];value.append(small);const note=document.createElement('p');note.className='kpi-note';note.textContent=k[3];const accent=document.createElement('span');accent.className='kpi-accent';accent.textContent=['◌','▦','∑','∿'][i];div.append(label,value,note,accent);return div;}));
    renderSeries(series,yearIndices);renderMonthly(series);renderCalendar(series);
  }
  function chartAxes(svg,x,y,width,height,pad,xTicks,xFormat){
    svg.selectAll('.chart-gridline').data(y.ticks(4)).join('line').attr('class','chart-gridline').attr('x1',pad.l).attr('x2',width-pad.r).attr('y1',v=>y(v)).attr('y2',v=>y(v));
    svg.append('g').attr('class','axis').attr('transform',`translate(${pad.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(0).tickPadding(9));
    let axis=d3.axisBottom(x).tickSize(0).tickPadding(12);if(xTicks)axis=axis.tickValues(xTicks);if(xFormat)axis=axis.tickFormat(xFormat);
    svg.append('g').attr('class','axis').attr('transform',`translate(0,${height-pad.b})`).call(axis);
  }
  function renderSeries(series,yearIndices){
    const svg=d3.select('#series-chart');svg.selectAll('*').remove();
    const w=760,h=245,p={l:38,r:15,t:12,b:30};let points=[],isDaily=state.period==='daily';
    if(isDaily)points=yearIndices.map(i=>({x:new Date(data.dates[i]+'T00:00:00Z'),value:series[i],label:dateLabel(data.dates[i])}));
    else if(state.period==='monthly'||state.period==='climatology'){
      const years=state.period==='climatology'?allYears.filter(y=>y>=state.reference[0]&&y<=state.reference[1]):[state.year];
      points=C.monthMeans(data.dates,series,years).map((v,i)=>({x:i,value:v,label:monthNames[i]}));
    }else if(state.period==='seasonal'){
      points=Object.keys(C.seasons).map((s,i)=>{const ix=C.selectDates(data.dates,{period:'seasonal',year:state.year,season:s});return{x:i,value:C.mean(ix.map(j=>series[j])),label:s};});
    }else points=allYears.map(y=>({x:y,value:C.mean(series.filter((_,i)=>+data.dates[i].slice(0,4)===y)),label:String(y)}));
    const max=Math.max(5,(d3.max(points,d=>d.value)||0)*1.2),y=d3.scaleLinear().domain([0,max]).nice().range([h-p.b,p.t]);
    const x=isDaily?d3.scaleUtc().domain([new Date(Date.UTC(state.year,0,1)),new Date(Date.UTC(state.year,11,31))]).range([p.l,w-p.r]):d3.scaleLinear().domain(d3.extent(points,d=>d.x)).range([p.l+10,w-p.r-8]);
    let ticks,formatter;
    if(isDaily){ticks=d3.utcMonth.every(2).range(new Date(Date.UTC(state.year,0,1)),new Date(Date.UTC(state.year+1,0,1)));formatter=d3.utcFormat('%b');}
    else if(state.period==='monthly'||state.period==='climatology'){ticks=points.map(d=>d.x);formatter=i=>monthNames[i];}
    else if(state.period==='seasonal'){ticks=points.map(d=>d.x);formatter=i=>points[i]?.label||'';}
    else {ticks=allYears.filter(y=>y%10===0||y===allYears.at(-1));formatter=d3.format('d');}
    chartAxes(svg,x,y,w,h,p,ticks,formatter);
    const area=d3.area().defined(d=>d.value!==null).x(d=>x(d.x)).y0(y(0)).y1(d=>y(d.value)).curve(d3.curveLinear);
    const line=d3.line().defined(d=>d.value!==null).x(d=>x(d.x)).y(d=>y(d.value)).curve(d3.curveLinear);
    svg.append('path').datum(points).attr('d',area).attr('fill','#e3ecd8');svg.append('path').datum(points).attr('d',line).attr('fill','none').attr('stroke','#4c8061').attr('stroke-width',1.8);
    if(isDaily){const value=series[dateIndex.get(state.date)];if(value!==null){const xx=x(new Date(state.date+'T00:00:00Z'));svg.append('line').attr('x1',xx).attr('x2',xx).attr('y1',p.t).attr('y2',h-p.b).attr('stroke','#9cac87').attr('stroke-dasharray','3 3');svg.append('circle').attr('cx',xx).attr('cy',y(value)).attr('r',4).attr('fill','#32694d').attr('stroke','white').attr('stroke-width',2);}}
    svg.append('g').selectAll('circle.tip').data(points.filter(d=>d.value!==null)).join('circle').attr('class','tip').attr('cx',d=>x(d.x)).attr('cy',d=>y(d.value)).attr('r',isDaily?4:5).attr('fill','transparent').append('title').text(d=>d.label+': '+pct(d.value)+'% blocked');
    $('series-title').textContent=isDaily?'Through the year':state.period==='annual'?'The longer record':state.period==='seasonal'?'Season by season':state.period==='climatology'?'The climatological year':'Month by month';
    $('series-subtitle').textContent=isDaily?'Daily blocked area · % of selected region':state.period==='annual'?'Annual mean blocked area (%) · incomplete final year marked below':state.period==='seasonal'?'Seasonal mean blocked area (%) · DJF uses previous December':'Monthly mean blocked area · % of selected region';
    $('series-year').textContent=state.period==='annual'?allYears[0]+'–'+allYears.at(-1):state.period==='climatology'?state.reference.join('–'):state.year;
    const sourceNote=data.meta.source==='synthetic'?' Synthetic demonstration.':'';
    $('series-note').textContent=state.period==='climatology'?`Monthly means over ${state.reference.join('–')}; the map can show a selected season or month.${sourceNote}`:state.period==='annual'?`${allYears.at(-1)} is incomplete: available through ${dateLabel(data.dates.at(-1))}.${sourceNote}`:data.dates.at(-1).startsWith(String(state.year))?`Available through ${dateLabel(data.dates.at(-1))}. Short ongoing runs remain pending.${sourceNote}`:'Only valid observations enter each period’s denominator.'+sourceNote;
  }
  function renderMonthly(series){
    const current=C.monthMeans(data.dates,series,[state.year]),reference=C.monthMeans(data.dates,series,allYears.filter(y=>y>=state.reference[0]&&y<=state.reference[1]));
    const svg=d3.select('#monthly-chart');svg.selectAll('*').remove();
    const w=440,h=245,p={l:32,r:7,t:13,b:31},x=d3.scaleBand().domain(d3.range(12)).range([p.l,w-p.r]).padding(.3),y=d3.scaleLinear().domain([0,Math.max(5,(d3.max([...current,...reference])||0)*1.18)]).nice().range([h-p.b,p.t]);
    chartAxes(svg,x,y,w,h,p,d3.range(12),i=>monthNames[i].slice(0,1));
    for(const [arr,color,offset] of [[reference,'#d5dfbd',.5],[current,'#54856b',0]])svg.append('g').selectAll('rect').data(arr.map((v,i)=>({v,i})).filter(d=>d.v!==null)).join('rect').attr('x',d=>x(d.i)+offset*x.bandwidth()).attr('y',d=>y(d.v)).attr('height',d=>y(0)-y(d.v)).attr('width',x.bandwidth()/2).attr('rx',1).attr('fill',color).append('title').text(d=>monthNames[d.i]+': '+pct(d.v)+'%');
    $('monthly-year-label').textContent=state.year;$('monthly-ref-label').textContent=data.meta.reference_available===false?'Reference unavailable':state.reference.join('–');
  }
  function renderCalendar(series){
    const svg=d3.select('#calendar-chart');svg.selectAll('*').remove();const w=1200,margin={l:35,t:26},cell=19,gap=3;
    const first=new Date(Date.UTC(state.year,0,1)),stop=new Date(Date.UTC(state.year+1,0,1)),days=d3.utcDays(first,stop),weekStart=d3.utcSunday.floor(first);
    const values=days.map(day=>{const date=d3.utcFormat('%Y-%m-%d')(day),ix=dateIndex.get(date);return{date,day,value:ix===undefined?null:series[ix],week:d3.utcSunday.count(weekStart,day),dow:day.getUTCDay()};});
    const max=Math.max(1,d3.max(values,d=>d.value)||1),color=d3.scaleSequential(d3.interpolateRgbBasis(['#eef1e6','#c0d2a4','#83a368','#33694d'])).domain([0,max]);
    svg.append('defs').append('pattern').attr('id','missing-hatch').attr('width',5).attr('height',5).attr('patternUnits','userSpaceOnUse').append('path').attr('d','M-1,1l2,-2M0,5L5,0M4,6l2,-2').attr('stroke','#dfe5d8').attr('stroke-width',1);
    const graph=svg.append('g').attr('transform',`translate(${margin.l},${margin.t})`);
    graph.selectAll('rect.day').data(values).join('rect').attr('class','day').attr('x',d=>d.week*(cell+gap)).attr('y',d=>d.dow*15).attr('width',cell).attr('height',12).attr('rx',2).attr('fill',d=>d.value===null?'url(#missing-hatch)':color(d.value)).attr('stroke',d=>d.date===state.date?'#245d46':d.value===null?'#ecf0e5':'none').attr('stroke-width',1.5).attr('tabindex',d=>d.value===null?null:0).attr('role',d=>d.value===null?null:'button').attr('aria-label',d=>dateLabel(d.date)+': '+(d.value===null?'unavailable':pct(d.value)+' percent blocked')).style('cursor',d=>d.value===null?'default':'pointer').on('click',(_,d)=>{if(d.value!==null){stopPlay();setDate(d.date);state.period='daily';update();}}).on('keydown',(event,d)=>{if(d.value!==null&&(event.key==='Enter'||event.key===' ')){event.preventDefault();setDate(d.date);state.period='daily';update();}}).append('title').text(d=>dateLabel(d.date)+' · '+(d.value===null?'No available data':pct(d.value)+'% area blocked'));
    for(let m=0;m<12;m++){const day=new Date(Date.UTC(state.year,m,1)),week=d3.utcSunday.count(weekStart,day);graph.append('text').attr('x',week*(cell+gap)).attr('y',-10).attr('font-size',9).attr('fill','#8c9c7e').text(monthNames[m]);}
    for(const [day,name] of [[1,'M'],[3,'W'],[5,'F']])graph.append('text').attr('x',-20).attr('y',day*15+10).attr('font-size',8).attr('fill','#96a38a').text(name);
    $('calendar-subtitle').textContent=`${state.year} · Each square is one day. Click a day to inspect its spatial pattern.`;
  }
  function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function exportCSV(){
    const series=getSeries(),name=state.region?.id||state.hemisphere+'-hemispheres';
    const header=['date','method','region','blocked_area_percent','data_source','source_provider','anomaly_reference','comparison_reference'];
    const refLoaded=data.meta.reference_available!==false;
    const rows=data.dates.flatMap((d,i)=>+d.slice(0,4)===state.year?[[d,state.method,name,series[i]===null?'':series[i].toFixed(5),data.meta.source,data.meta.source_provider||'CDS',refLoaded?data.meta.anomaly_reference.join('-'):'not_loaded',refLoaded?state.reference.join('-'):'not_loaded'].join(',')]:[]);
    download(`blocking-${name}-${state.method}-${state.year}.csv`,[header.join(','),...rows].join('\n'),'text/csv;charset=utf-8');showToast('Daily regional record downloaded.');
  }
  function exportMap(){
    const svg=$('world-map').cloneNode(true);svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('viewBox','0 -60 1040 525');
    const title=document.createElementNS('http://www.w3.org/2000/svg','text');title.setAttribute('x','43');title.setAttribute('y','-33');title.setAttribute('font-size','17');title.setAttribute('fill','#183e38');title.textContent=$('map-title').textContent+' · '+periodTitle()+' · '+state.method.toUpperCase();svg.prepend(title);
    const note=document.createElementNS('http://www.w3.org/2000/svg','text');note.setAttribute('x','43');note.setAttribute('y','-9');note.setAttribute('font-size','11');note.setAttribute('fill','#8b7652');note.textContent=data.meta.source==='synthetic'?'SYNTHETIC DEMONSTRATION — NOT ERA5 OBSERVATIONS':'ERA5/ERA5T · 00:00 UTC · Shelke & Renwick (2026)';svg.append(note);
    const legend=document.createElementNS('http://www.w3.org/2000/svg','text');legend.setAttribute('x','43');legend.setAttribute('y','460');legend.setAttribute('font-size','10');legend.setAttribute('fill','#667b58');legend.textContent=palette().label+' · thresholds: '+palette().thresholds.join(', ')+' · outline: confirmed blocking';svg.append(legend);
    svg.querySelectorAll('.map-label').forEach(el=>{el.setAttribute('fill','#83977a');el.setAttribute('font-size','9');});svg.querySelectorAll('.map-gridline').forEach(el=>{el.setAttribute('fill','none');el.setAttribute('stroke','#dce4d8');el.setAttribute('stroke-width','.65');});
    download(`blocking-map-${state.method}-${state.period}-${state.date}.svg`,new XMLSerializer().serializeToString(svg),'image/svg+xml');showToast('Map downloaded as an editable SVG.');
  }
  function update(){
    syncControls();renderMap();renderStatistics();
    const parameters=new URLSearchParams({method:state.method,view:state.period,date:state.date,region:state.region?.id||'global',hemisphere:state.hemisphere,reference:state.reference.join('-'),month:state.month,season:state.season,slice:state.climateSlice,layer:state.layer});
    history.replaceState(null,'','#'+parameters.toString());
  }
  try{
    if(!('DecompressionStream' in window))throw new Error('This preview needs a recent browser with gzip decompression support.');
    if(!window.BLOCKING_ERA5_GZIP)throw new Error('The observed ERA5 archive is unavailable. The dashboard will not substitute demonstration data.');
    data=decodeData(await unpack(window.BLOCKING_ERA5_GZIP));
    if(data.schema!==1)throw new Error('Unsupported data schema');
    ncell=data.grid.latitudes.length*data.grid.longitudes.length;
    dateIndex=new Map(data.dates.map((d,i)=>[d,i]));fieldIndex=new Map((data.fields?.dates||[]).map((d,i)=>[d,i]));allYears=[...new Set(data.dates.map(d=>+d.slice(0,4)))];
    state.reference=[...data.meta.anomaly_reference];setDate(data.dates.at(-1));
    const hash=new URLSearchParams(location.hash.slice(1));
    if(['ppa','tr'].includes(hash.get('method')))state.method=hash.get('method');
    if(['daily','monthly','seasonal','annual','climatology'].includes(hash.get('view')))state.period=hash.get('view');
    if(dateIndex.has(hash.get('date')))setDate(hash.get('date'));
    if(+hash.get('month')>=1&&+hash.get('month')<=12)state.month=+hash.get('month');
    if(['DJF','MAM','JJA','SON'].includes(hash.get('season')))state.season=hash.get('season');
    if(['all','DJF','MAM','JJA','SON',...Array.from({length:12},(_,i)=>String(i+1))].includes(hash.get('slice')))state.climateSlice=hash.get('slice');
    if(['anomaly','blocked','z500'].includes(hash.get('layer')))state.layer=hash.get('layer');
    if(['both','nh','sh'].includes(hash.get('hemisphere')))state.hemisphere=hash.get('hemisphere');
    const region=data.regions.find(r=>r.id===hash.get('region'));if(region){state.region=region;state.hemisphere=region.hemisphere;}
    const ref=(hash.get('reference')||'').split('-').map(Number);if(ref.length===2&&ref[0]<=ref[1]&&ref[0]>=allYears[0]&&dateIndex.has(ref[1]+'-12-31'))state.reference=ref;
    const supportedMethods=data.meta.available_methods||['ppa','tr'];
    if(!supportedMethods.includes(state.method))state.method=supportedMethods[0];
    if(state.period==='climatology'&&data.meta.reference_available===false)state.period='daily';
    initControls();
    const synthetic=data.meta.source==='synthetic';
    $('data-notice').querySelector('strong').textContent=synthetic?'Demonstration data':'ERA5 / ERA5T';
    $('notice-detail').textContent=synthetic?'Synthetic fields let you explore every control. These are not observed blocking conditions.':`Latest verified sample: ${dateLabel(data.meta.latest_date)} · ${data.meta.source_provider||'Copernicus Climate Data Store'}. ${data.meta.reference_available===false?'Recent sample: TR and Z500 available; PPA and climatology await the historical reference.':'Recent ERA5T is preliminary.'}`;
    $('footer-status').textContent=`Unpublished · ${synthetic?'demonstration':dateLabel(data.meta.latest_date)}`;
    $('dialog-data-state').textContent=synthetic?'This preview uses deterministic synthetic fields, not ERA5. Values demonstrate the interface and are not weather observations.':`Source: ${data.meta.source_provider||'Copernicus Climate Data Store'}; ERA5 pressure-level geopotential at 500 hPa. Latest sample: ${data.meta.latest_date} · ${data.meta.sample_time}. ERA5T may be revised. Detection grid: ${data.meta.grid_degrees}°${data.meta.native_grid_degrees?' sampled from '+data.meta.native_grid_degrees+'° fields':''}. ${data.meta.final_era5_through?'Finalized ERA5 through '+data.meta.final_era5_through+'.':''}`;
    update();$('loading').hidden=true;
    // Read-only diagnostics for review and automated quality checks.
    window.BlockingObservatory={state,data,selectRegion,update,getSeries,mapValues};
  }catch(error){console.error(error);$('loading').querySelector('p').textContent='The archive could not be loaded.';$('loading').querySelector('small').textContent=error.message;$('loading').querySelector('.loading-orbit').style.display='none';}
})();
