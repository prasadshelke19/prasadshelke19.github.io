const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../core.js');
test('regions crossing the date line include both longitude sides',()=>{
 assert.equal(C.inBounds(175,-50,[150,-65,-160,-35]),true);
 assert.equal(C.inBounds(-175,-50,[150,-65,-160,-35]),true);
 assert.equal(C.inBounds(0,-50,[150,-65,-160,-35]),false);
});
test('tropics and out-of-domain latitudes never enter weighted denominators',()=>{
 const cells=C.cellsFor({latitudes:[80,60,0,-60,-80],longitudes:[0]},null);
 assert.deepEqual(cells.map(c=>c.index),[1,3]);
 assert.ok(Math.abs(cells[0].weight-.5)<1e-12);
});
test('missing grid cells are excluded rather than counted as unblocked',()=>{
 const data={grid:{latitudes:[45],longitudes:[0,5]},dates:['2026-01-01','2026-01-02'],masks:{ppa:Uint8Array.from([1]),valid_ppa:Uint8Array.from([1])}};
 assert.deepEqual(C.areaSeries(data,'ppa',[{index:0,weight:1},{index:1,weight:1}]),[100,null]);
 const values=C.aggregateGrid(data,'ppa',[0,1]);
 assert.equal(values[0],100);assert.ok(Number.isNaN(values[1]));
});
test('DJF belongs to January year, including the previous December',()=>{
 const dates=['2024-12-31','2025-01-01','2025-02-28','2025-12-01'];
 assert.deepEqual(C.selectDates(dates,{period:'seasonal',year:2025,season:'DJF'}),[0,1,2]);
 assert.deepEqual(C.selectDates(dates,{period:'climatology',reference:[2025,2025],climateSlice:'DJF'}),[0,1,2]);
 assert.equal(C.expectedDays({period:'seasonal',year:2024,season:'DJF'}),91);
});
test('annual and monthly denominators respect leap years and real day counts',()=>{
 assert.equal(C.expectedDays({period:'annual',year:2024}),366);
 assert.equal(C.expectedDays({period:'annual',year:2025}),365);
 assert.equal(C.expectedDays({period:'monthly',year:2024,month:2}),29);
 assert.equal(C.expectedDays({period:'monthly',year:2025,month:2}),28);
});
test('climatology filters years and months without treating future days as zero',()=>{
 const dates=['1990-01-01','1991-01-01','1991-07-01','1992-01-01'];
 assert.deepEqual(C.selectDates(dates,{period:'climatology',reference:[1991,1991],climateSlice:'1'}),[1]);
 assert.deepEqual(C.monthMeans(dates,[5,10,20,null],[1991]),[10,null,null,null,null,null,20,null,null,null,null,null]);
});
