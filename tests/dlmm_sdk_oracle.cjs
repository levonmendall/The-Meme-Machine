/* Optional developer oracle. No production Node dependency or sidecar.
 * npm install --prefix <temporary directory> bn.js@5.2.1 typescript@5.0.4
 * NODE_PATH=<temporary directory>/node_modules node tests/dlmm_sdk_oracle.cjs <SDK checkout>
 * Executes the official source exports via TypeScript transpilation, not translated formulas.
 */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const ts=require('typescript'),BN=require('bn.js');
const root=process.argv[2],cache={},hashes={};
const constants={SCALE_OFFSET:64,BASIS_POINT_MAX:10000,FEE_PRECISION:new BN(1000000000),
 MAX_FEE_RATE:new BN(100000000),LIMIT_ORDER_FEE_SHARE:new BN(5000),U64_MAX:new BN(2).pow(new BN(64)).subn(1)};
function load(name){
 if(cache[name])return cache[name];
 const filename=path.join(root,'ts-client/src/dlmm/helpers',name+'.ts');
 const source=fs.readFileSync(filename,'utf8');
 hashes['ts-client/src/dlmm/helpers/'+name+'.ts']=crypto.createHash('sha256').update(source).digest('hex');
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
 const module={exports:{}};
 const req=(id)=>{
   if(id==='bn.js')return BN;
   if(id==='@coral-xyz/anchor')return {BN};
   if(id==='../constants')return constants;
   if(['./math','./fee','./u64xu64_math'].includes(id))return load(id.slice(2));
   // Unused dependency bindings from the large math.ts source. The executed
   // exports below do not access Decimal, DLMM or weight helpers.
   if(['decimal.js','..','./weight'].includes(id))return {};
   throw new Error('Unexpected oracle dependency '+id);
 };
 new Function('require','module','exports',code)(req,module,module.exports);
 return cache[name]=module.exports;
}
const math=load('math'),fee=load('fee'),bin=load('bin');
const prices=[];
for(const step of [1,10,25,250,1000])for(const id of [-1000,-78,-2,-1,0,1,2,1000]){
 try{prices.push({step,id,value:math.getQPriceFromId(new BN(id),new BN(step)).toString()});}catch(e){}
}
const fees=[],swaps=[];
for(const step of [10,250])for(const volatility of [0,10000,350000]){
 const s={baseFactor:10000,baseFeePowerFactor:0,variableFeeControl:1000,protocolShare:2000};
 const v={volatilityAccumulator:volatility};
 fees.push({step,volatility,rate:fee.getTotalFee(step,s,v).toString()});
 for(const id of [-2,0,2])for(const direction of [true,false])for(const input of [1,999,1000000,450000000]){
  const b={amountX:new BN(200000000),amountY:new BN(200000000),price:math.getQPriceFromId(new BN(id),new BN(step)),
    openOrderAmount:new BN(0),processedOrderRemainingAmount:new BN(0),limitOrderAskSide:0};
  const q=bin.swapExactInQuoteAtBin(b,step,s,v,new BN(input),direction,false,true);
  swaps.push({step,volatility,id,direction,input,amountIn:q.amountIn.toString(),
    amountOut:q.amountOut.toString(),lpFee:q.fee.toString(),protocolFee:q.protocolFee.toString()});
 }
}
console.log(JSON.stringify({source:'MeteoraAg/dlmm-sdk',commit:'576919e3e4368e542c402f000b4264724f7f23ec',
 package:'@meteora-ag/dlmm@1.9.14',hashes,prices,fees,swaps},null,2));
