javascript:(()=>{
  /* Are Scanner Bookmarklet (PC JRA版) */
  const C={minOdds:100,maxMargin:1.0,maxPast:5,backCount:3};
  const Z='０１２３４５６７８９．－＋，　',H='0123456789.-+, ';
  const half=s=>String(s||'').replace(/[０-９．－＋，　]/g,c=>{const i=Z.indexOf(c);return i>=0?H[i]:c});
  const clean=s=>half(s).replace(/ /g,' ').replace(/\s+/g,' ').trim();
  const JRA=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉'];
  const clsFn=s=>{
    s=clean(s);
    if(/未勝利/.test(s))return'未勝利';
    if(/新馬/.test(s))return'新馬';
    if(/(?:^|[^0-9])3\s*勝/.test(s))return'3勝';
    if(/(?:^|[^0-9])2\s*勝/.test(s))return'2勝';
    if(/(?:^|[^0-9])1\s*勝/.test(s))return'1勝';
    if(/1600万/.test(s))return'3勝';
    if(/1000万/.test(s))return'2勝';
    if(/500万/.test(s))return'1勝';
    if(/オープン|OP|OPEN|Listed|リステッド|重賞|GⅠ|GⅡ|GⅢ|G[1-3]|Jpn[1-3]/i.test(s))return'OP重賞';
    return'';
  };

  /* ヘッダーからレース情報取得 */
  const body=document.body.innerText||'';
  let hS=body.indexOf('発走時刻');
  if(hS<0)hS=body.indexOf('ここから本文です');
  if(hS<0)hS=0;
  let hE=body.indexOf('馬 番');
  if(hE<0)hE=body.indexOf('馬名 / 単勝');
  if(hE<0)hE=body.indexOf('馬名');
  if(hE<0||hE<hS)hE=Math.min(body.length,hS+6000);
  const header=clean(body.slice(hS,hE));
  const currentCls=clsFn(header);
  let curSf='',curDist=0;
  const cm1=header.match(/([\d,]+)\s*メートル\s*[（(]\s*(ダ(?:ート)?|芝)/);
  const cm2=header.match(/(ダ(?:ート)?|芝)\s*([\d,]+)\s*(?:m|メートル)/);
  if(cm1){curDist=parseInt(cm1[1].replace(/,/g,''));curSf=cm1[2].startsWith('ダ')?'ダ':'芝';}
  else if(cm2){curSf=cm2[1].startsWith('ダ')?'ダ':'芝';curDist=parseInt(cm2[2].replace(/,/g,''));}

  /* 馬検出 */
  const txtAfter=(n,len)=>{try{const r=document.createRange();r.setStartAfter(n);r.setEnd(document.body,document.body.childNodes.length);return clean(r.toString()).slice(0,len||3000)}catch{return''}};
  const txtRange=(a,b)=>{try{const r=document.createRange();r.setStartBefore(a);if(b)r.setEndBefore(b);else r.setEnd(document.body,document.body.childNodes.length);return r.toString()}catch{return''}};
  const anchors=[...document.querySelectorAll('a')].filter(a=>clean(a.textContent).length>=2);
  const horses=[];
  for(const a of anchors){
    const af=txtAfter(a,3000);
    const m=af.match(/^(\d{1,4}(?:\.\d+)?)\s*[\(（]\s*\d+\s*番人気/);
    if(!m)continue;
    if(!/着/.test(af))continue;
    if(!/\d{4}年\d{1,2}月\d{1,2}日/.test(af))continue;
    horses.push({a,odds:Number(m[1]),name:clean(a.textContent)});
  }

  /* 過去レースパース */
  const parsePast=block=>{
    const lines=String(block).split(/\n+/).map(clean).filter(Boolean);
    const idx=[];
    for(let i=0;i<lines.length;i++)if(/^\d{4}年\d{1,2}月\d{1,2}日/.test(lines[i]))idx.push(i);
    const races=[];
    for(let k=0;k<idx.length;k++){
      const run=lines.slice(idx[k],idx[k+1]??lines.length).join(' ');
      const rcls=clsFn(run);
      const margins=[...run.matchAll(/[\(（]\s*(-?\d+(?:\.\d+)?)\s*[\)）]/g)].map(x=>Number(x[1])).filter(Number.isFinite);
      const margin=margins.length>0?Math.min(...margins.map(Math.abs)):null;
      let dist=0,sf='';
      const dm=run.match(/(ダ(?:ート)?|芝)\s*(\d{3,4})/);
      if(dm){sf=dm[1].startsWith('ダ')?'ダ':'芝';dist=parseInt(dm[2]);}
      const isJRA=JRA.some(t=>run.includes(t));
      let lc=0,f3=0;
      const cf=run.match(/(\d{1,2}(?:\s+\d{1,2}){1,3})\s+3F\s*(\d{2}\.\d)/);
      if(cf){const cs=cf[1].trim().split(/\s+/);lc=parseInt(cs[cs.length-1]);f3=parseFloat(cf[2]);}
      else{
        const c4=run.match(/(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})/);
        if(c4)lc=parseInt(c4[4]);
        else{const c3=run.match(/(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})/);if(c3)lc=parseInt(c3[3]);}
        const f3m=run.match(/(?:上[がりり]*\s*)?3F\s*(\d{2}\.\d)/);
        if(f3m)f3=parseFloat(f3m[1]);
      }
      let fs=0;
      const fsm=run.match(/(\d+)\s*頭/);
      if(fsm)fs=parseInt(fsm[1]);
      races.push({cls:rcls,margin,dist,sf,isJRA,lc,f3,fs});
    }
    return races;
  };

  /* スタイル */
  let st=document.getElementById('_areSt');
  if(!st){st=document.createElement('style');st.id='_areSt';document.head.appendChild(st);}
  st.textContent='.are_m{background:#fff176!important;box-shadow:inset 0 0 0 3px #f9a825!important;border-radius:4px!important;display:inline-block!important;padding:2px 6px!important}.are_d{background:#90caf9!important;box-shadow:inset 0 0 0 3px #1976d2!important;border-radius:4px!important;display:inline-block!important;padding:2px 6px!important}.are_b{background:#ce93d8!important;box-shadow:inset 0 0 0 3px #7b1fa2!important;border-radius:4px!important;display:inline-block!important;padding:2px 6px!important}';
  document.querySelectorAll('.are_m,.are_d,.are_b').forEach(e=>{e.classList.remove('are_m','are_d','are_b');delete e.dataset.are});

  /* フィルタリング */
  let nM=0,nD=0,nB=0;
  const rows=[];
  for(let i=0;i<horses.length;i++){
    const o=horses[i],next=horses[i+1]?.a;
    const block=txtRange(o.a,next);
    const past=parsePast(block);
    let hitM=false,hitD=false;

    /* 1.0秒スキャン: 単勝100倍以上 + 同クラス近5走で着差1.0秒以内 */
    if(o.odds>=C.minOdds&&currentCls){
      for(let k=0;k<Math.min(C.maxPast,past.length);k++){
        if(past[k].cls===currentCls&&past[k].margin!==null&&past[k].margin<=C.maxMargin){hitM=true;break;}
      }
    }

    /* 距離延長スキャン: 今走ダート + 前走ダート短距離 + 後方 + 上がり3F有効 */
    if(curSf==='ダ'&&curDist>0&&past.length>0){
      const pr=past[0];
      if(pr.isJRA&&pr.sf==='ダ'&&pr.dist>0&&pr.dist<curDist&&pr.f3>0&&pr.fs>0&&pr.lc>0){
        const th=pr.fs-C.backCount+1;
        if(th>=1&&pr.lc>=th)hitD=true;
      }
    }

    if(!hitM&&!hitD)continue;
    const c=hitM&&hitD?'are_b':hitM?'are_m':'are_d';
    o.a.classList.add(c);o.a.dataset.are='1';
    const type=hitM&&hitD?'両方':hitM?'1.0秒':'距離延長';
    let tip='Are Scanner: '+type;
    if(hitM)tip+=' | '+currentCls+'同クラス着差≤'+C.maxMargin+'秒 / '+o.odds+'倍';
    if(hitD){const pr=past[0];tip+=' | ダ'+pr.dist+'→'+curDist+'m / 4角'+pr.lc+'番手('+pr.fs+'頭) / 3F'+pr.f3;}
    o.a.title=tip;
    rows.push({馬名:o.name,単勝:o.odds,種別:type});
    if(hitM&&hitD)nB++;else if(hitM)nM++;else nD++;
  }

  console.log('[Are Scanner]',{class:currentCls,surface:curSf,dist:curDist,horses:horses.length});
  if(rows.length)console.table(rows);
  alert('Are Scanner 完了\n現クラス: '+(currentCls||'不明')+'\nコース: '+(curSf||'?')+curDist+'m\n検出馬: '+horses.length+'頭\n\n■ 1.0秒 (黄): '+nM+'\n■ 距離延長 (青): '+nD+'\n■ 両方 (紫): '+nB+'\n合計: '+(nM+nD+nB)+'頭\n\n馬名に色をつけました。\nマウスオーバーで詳細。');
})();
