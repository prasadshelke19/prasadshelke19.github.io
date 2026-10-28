/* Shared, dependency-free calculations; also exercised with node --test. */
(function(root){
  'use strict';
  const seasons = {DJF:[12,1,2],MAM:[3,4,5],JJA:[6,7,8],SON:[9,10,11]};
  const bit = (bytes,offset) => (bytes[offset >>> 3] >>> (offset & 7)) & 1;
  const yearOf = d => +d.slice(0,4);
  const monthOf = d => +d.slice(5,7);
  function inBounds(lon,lat,bounds){
    const [west,south,east,north]=bounds;
    return lat>=south && lat<=north && (west<=east ? lon>=west&&lon<=east : lon>=west||lon<=east);
  }
  function cellsFor(grid,region,hemisphere='both'){
    const result=[],nx=grid.longitudes.length;
    grid.latitudes.forEach((lat,j)=>{
      if(Math.abs(lat)<30||Math.abs(lat)>75||(hemisphere==='nh'&&lat<0)||(hemisphere==='sh'&&lat>0))return;
      grid.longitudes.forEach((lon,i)=>{
        if(!region||inBounds(lon,lat,region.bounds))result.push({index:j*nx+i,weight:Math.cos(lat*Math.PI/180)});
      });
    });
    return result;
  }
  function areaSeries(data,method,cells){
    const ncell=data.grid.latitudes.length*data.grid.longitudes.length;
    const mask=data.masks[method],valid=data.masks['valid_'+method];
    return data.dates.map((_,d)=>{
      let numerator=0,denominator=0;
      const offset=d*ncell;
      for(const cell of cells){
        if(bit(valid,offset+cell.index)){
          denominator+=cell.weight;
          numerator+=bit(mask,offset+cell.index)*cell.weight;
        }
      }
      return denominator>0?100*numerator/denominator:null;
    });
  }
  function selectDates(dates,{period='daily',date,year,month,season='DJF',reference=[1980,2014],climateSlice='all'}){
    year=+year;month=+month;
    return dates.flatMap((d,i)=>{
      const y=yearOf(d),m=monthOf(d);
      let yes=false;
      if(period==='daily')yes=d===date;
      if(period==='monthly')yes=y===year&&m===month;
      if(period==='annual')yes=y===year;
      if(period==='seasonal'){
        const seasonYear=m===12&&season==='DJF'?y+1:y;
        yes=seasonYear===year&&seasons[season].includes(m);
      }
      if(period==='climatology'){
        const sliceMonths=seasons[climateSlice]||(climateSlice==='all'?null:[+climateSlice]);
        const referenceYear=climateSlice==='DJF'&&m===12?y+1:y;
        yes=referenceYear>=reference[0]&&referenceYear<=reference[1]&&(!sliceMonths||sliceMonths.includes(m));
      }
      return yes?[i]:[];
    });
  }
  function aggregateGrid(data,method,indices){
    const n=data.grid.latitudes.length*data.grid.longitudes.length;
    const result=new Float32Array(n),counts=new Uint32Array(n);
    for(const day of indices){
      const offset=day*n;
      for(let c=0;c<n;c++)if(bit(data.masks['valid_'+method],offset+c)){
        counts[c]++;result[c]+=bit(data.masks[method],offset+c);
      }
    }
    for(let c=0;c<n;c++)result[c]=counts[c]?100*result[c]/counts[c]:NaN;
    return result;
  }
  function mean(values){const v=values.filter(x=>x!==null&&Number.isFinite(x));return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;}
  function monthMeans(dates,series,years){
    return Array.from({length:12},(_,m)=>mean(series.filter((_,i)=>years.includes(yearOf(dates[i]))&&monthOf(dates[i])===m+1)));
  }
  function expectedDays({period,year,month,season,reference,climateSlice='all'}){
    const daysInMonth=(y,m)=>new Date(Date.UTC(y,m,0)).getUTCDate();
    if(period==='daily')return 1;
    if(period==='monthly')return daysInMonth(+year,+month);
    if(period==='annual')return daysInMonth(+year,2)===29?366:365;
    if(period==='seasonal')return seasons[season].reduce((sum,m)=>sum+daysInMonth(season==='DJF'&&m===12?year-1:+year,m),0);
    if(period==='climatology'){
      let n=0;
      for(let y=reference[0];y<=reference[1];y++){
        const months=seasons[climateSlice]||(climateSlice==='all'?Array.from({length:12},(_,i)=>i+1):[+climateSlice]);
        n+=months.reduce((s,m)=>s+daysInMonth(climateSlice==='DJF'&&m===12?y-1:y,m),0);
      }
      return n;
    }
    return 0;
  }
  const api={bit,inBounds,cellsFor,areaSeries,selectDates,aggregateGrid,mean,monthMeans,expectedDays,seasons,yearOf,monthOf};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.BlockingCore=api;
})(typeof window!=='undefined'?window:globalThis);
