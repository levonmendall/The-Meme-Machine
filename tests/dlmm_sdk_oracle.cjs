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
function extractFunction(source,name){
 const start=source.indexOf('function '+name+'(');
 if(start<0)throw new Error('Missing official helper '+name);
 const body=source.indexOf('{',start);let depth=0;
 for(let i=body;i<source.length;i++){
  if(source[i]==='{')depth++;
  else if(source[i]==='}' && --depth===0)return source.slice(start,i+1);
 }
 throw new Error('Unclosed official helper '+name);
}
function loadAccounting(){
 const rel='ts-client/src/dlmm/helpers/rebalance/rebalancePosition.ts';
 const source=fs.readFileSync(path.join(root,rel),'utf8');
 hashes[rel]=crypto.createHash('sha256').update(source).digest('hex');
 const snippet='import BN from "bn.js";\nimport { SCALE_OFFSET } from "../constants";\n'+
  'import { getQPriceFromId } from "./math";\n'+extractFunction(source,'getLiquidity')+'\n'+
  extractFunction(source,'simulateDepositBin')+'\nexport { getLiquidity, simulateDepositBin };';
 const code=ts.transpileModule(snippet,{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
 const module={exports:{}};
 const req=(id)=>id==='bn.js'?BN:id==='../constants'?constants:id==='./math'?load('math'):(()=>{throw new Error('Unexpected accounting dependency '+id)})();
 new Function('require','module','exports',code)(req,module,module.exports);
 return module.exports;
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
const accounting=[],officialAccounting=loadAccounting();
for(const step of [1,25,250])for(const id of [-2,0,2])for(const amount of [1,2,999,1000000]){
 const qprice=math.getQPriceFromId(new BN(id),new BN(step));
 const useX=id>=0,binX=new BN(useX?1000003:0),binY=new BN(useX?0:1000003);
 const inX=new BN(useX?amount:0),inY=new BN(useX?0:amount);
 const supply=new BN(1000000).shln(64).addn(12345);
 const inLiquidity=officialAccounting.getLiquidity(inX,inY,qprice);
 const binLiquidity=officialAccounting.getLiquidity(binX,binY,qprice);
 const share=inLiquidity.mul(supply).div(binLiquidity);
 const postSupply=supply.add(share),postX=binX.add(inX),postY=binY.add(inY);
 const simulated=officialAccounting.simulateDepositBin(new BN(id),new BN(step),inX,inY,
  {amountX:binX,amountY:binY,liquiditySupply:supply});
 const feeDelta=new BN(amount).mul(new BN('18446744073709551617'));
 accounting.push({step,id,amount,binX:binX.toString(),binY:binY.toString(),supply:supply.toString(),
  inX:inX.toString(),inY:inY.toString(),price:qprice.toString(),inLiquidity:inLiquidity.toString(),
  binLiquidity:binLiquidity.toString(),share:share.toString(),
  withdrawX:share.mul(postX).div(postSupply).toString(),withdrawY:share.mul(postY).div(postSupply).toString(),
  sdkSimulatedX:simulated.amountXIntoBin.toString(),sdkSimulatedY:simulated.amountYIntoBin.toString(),
  feeDelta:feeDelta.toString(),claim:math.mulShr(share.shrn(64),feeDelta,64,math.Rounding.Down).toString()});
}
console.log(JSON.stringify({source:'MeteoraAg/dlmm-sdk',commit:'576919e3e4368e542c402f000b4264724f7f23ec',
 package:'@meteora-ag/dlmm@1.9.14',hashes,prices,fees,swaps,accounting},null,2));
