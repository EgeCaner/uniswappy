from ...utils.interfaces import IExchange
from ...utils.data import FactoryData
from ...utils.data import UniswapExchangeData
from ...erc import LPERC20
from ...utils.tools.v3.Shared import *
from ...utils.tools.v3 import Position
from ...utils.tools.v3 import Tick
from ...utils.tools.v3 import SqrtPriceMath
from ...utils.tools.v3 import LiquidityMath 
from ...utils.tools.v3 import SwapMath, TickMath, SafeMath, FullMath
import math
from decimal import Decimal
from dataclasses import dataclass

MINIMUM_LIQUIDITY = 1e-15
GWEI_PRECISION = 18

@dataclass
class Slot0:
    ## the current price
    sqrtPriceX96: int
    ## the current tick
    tick: int
    ## the current protocol fee as a percentage of the swap fee taken on withdrawal
    ## represented as an integer denominator (1#x)%
    feeProtocol: int
    
@dataclass
class ModifyPositionParams:
    ## the address that owns the position
    owner: str
    ## the lower and upper tick of the position
    tickLower: int
    tickUpper: int
    ## any change in liquidity
    liquidityDelta: int  

@dataclass
class SwapCache:
    ## the protocol fee for the input token
    feeProtocol: int
    ## liquidity at the beginning of the swap
    liquidityStart: int

MINIMUM_LIQUIDITY = 1e-15

@dataclass
class Slot0:
    ## the current price
    sqrtPriceX96: int
    ## the current tick
    tick: int
    ## the current protocol fee as a percentage of the swap fee taken on withdrawal
    ## represented as an integer denominator (1#x)%
    feeProtocol: int
    
@dataclass
class ModifyPositionParams:
    ## the address that owns the position
    owner: str
    ## the lower and upper tick of the position
    tickLower: int
    tickUpper: int
    ## any change in liquidity
    liquidityDelta: int  

@dataclass
class SwapCache:
    ## the protocol fee for the input token
    feeProtocol: int
    ## liquidity at the beginning of the swap
    liquidityStart: int

@dataclass
class SwapState:
    ## the amount remaining to be swapped in#out of the input#output asset
    amountSpecifiedRemaining: int
    ## the amount already swapped out#in of the output#input asset
    amountCalculated: int
    ## current sqrt(price)
    sqrtPriceX96: int
    ## the tick associated with the current price
    tick: int
    ## the global fee growth of the input token
    feeGrowthGlobalX128: int
    ## amount of input token paid as protocol fee
    protocolFee: int
    ## the current liquidity in range
    liquidity: int

    ## list of ticks crossed during the swap
    ticksCrossed: list

@dataclass
class StepComputations:
    ## the price at the beginning of the step
    sqrtPriceStartX96: int
    ## the next tick to swap to from the current tick in the swap direction
    tickNext: int
    ## whether tickNext is initialized or not
    initialized: bool
    ## sqrt(price) for the next tick (1#0)
    sqrtPriceNextX96: int
    ## how much is being swapped in in this step
    amountIn: int
    ## how much is being swapped out
    amountOut: int
    ## how much fee is being paid in
    feeAmount: int

@dataclass
class ProtocolFees:
    token0: int
    token1: int

class UniswapV3Exchange(IExchange, LPERC20):
                       
    def __init__(self, factory_struct: FactoryData, exchg_struct: UniswapExchangeData):
        super().__init__(exchg_struct.tkn0.token_name+exchg_struct.tkn1.token_name, exchg_struct.address)
        self.factory = factory_struct
        self.token0 = exchg_struct.tkn0.token_name     
        self.token1 = exchg_struct.tkn1.token_name       
        self.reserve0 = 0             
        self.reserve1 = 0 
        self.fee = exchg_struct.fee
        self.fee0_arr = []
        self.fee1_arr = []
        self.aggr_fee0 = 0
        self.aggr_fee1 = 0
        self.collected_fee0 = 0
        self.collected_fee1 = 0              
        self.name =  f"{self.token0}-{self.token1}"
        self.symbol = exchg_struct.symbol
        self.precision = exchg_struct.precision
        self.last_liquidity_deposit = 0
        self.total_supply = 0
        self.tick_spacing = 1000
        self.slot0 = Slot0(0, 0, 0)
        self.positions = {}
        self.ticks = {}
        self.feeGrowthGlobal0X128 = 0
        self.feeGrowthGlobal1X128 = 0  
        self.protocolFees = ProtocolFees(0, 0)
        self.tickSpacing = exchg_struct.tick_spacing
        self.maxLiquidityPerTick = Tick.tickSpacingToMaxLiquidityPerTick(self.tickSpacing)      

    def summary(self):

        print(f"Exchange {self.name} ({self.symbol})")

        if (self.precision == UniswapExchangeData.TYPE_GWEI):
            print(f"Reserves: {self.token0} = {self.reserve0}, {self.token1} = {self.reserve1}")
            print(f"Liquidity: {self.total_supply} \n")
        else:  
            print(f"Reserves: {self.token0} = {self.gwei2dec(self.reserve0)}, {self.token1} = {self.gwei2dec(self.reserve1)}")
            print(f"Liquidity: {self.gwei2dec(self.total_supply)} \n")            

    def dec2gwei(self, tkn_amt, precision=None):
        precision = GWEI_PRECISION if precision == None else precision
        return int(Decimal(str(tkn_amt))*Decimal(str(10**precision)))
    
    def gwei2dec(self, dec_amt, precision=None):   
        precision = GWEI_PRECISION if precision == None else precision
        return float(Decimal(str(dec_amt))/Decimal(str(10**precision)))  

    def checkTicks(self, tickLower, tickUpper):
        checkInputTypes(int24=(tickLower, tickUpper))
        assert tickLower < tickUpper, "TLU"
        assert tickLower >= TickMath.MIN_TICK, "TLM"
        assert tickUpper <= TickMath.MAX_TICK, "TUM"    

    def initialize(self, sqrtPriceX96):
        checkInputTypes(uint160=(sqrtPriceX96))
        assert self.slot0.sqrtPriceX96 == 0, "AI"

        tick = TickMath.getTickAtSqrtRatio(sqrtPriceX96)

        self.slot0 = Slot0(
            sqrtPriceX96,
            tick,
            0,
        )
    
    def mint(self, recipient, tickLower, tickUpper, amount):  

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        checkInputTypes(
            accounts=(recipient), int24=(tickLower, tickUpper), uint128=(amount)
        )
        assert amount > 0

        (_, amount0Int, amount1Int) = self._modifyPosition(
            ModifyPositionParams(recipient, tickLower, tickUpper, amount)
        )

        amount0 = toUint256(abs(amount0Int))
        amount1 = toUint256(abs(amount1Int))
        
        tokens = self.factory.token_from_exchange[self.name]
        assert tokens.get(self.token0) and tokens.get(self.token1), 'UniswapV3: TOKEN_UNAVAILABLE' 

        balance0Before = tokens.get(self.token0).token_total
        balance1Before = tokens.get(self.token1).token_total 
        
        tokens.get(self.token0).deposit(recipient, amount0)
        tokens.get(self.token1).deposit(recipient, amount1)  

        balanceA = tokens.get(self.token0).token_total
        balanceB = tokens.get(self.token1).token_total

        self._update(balanceA, balanceB)
    
        assert balance0Before + amount0 <= tokens.get(self.token0).token_total, 'UniswapV3: M0' 
        assert balance1Before + amount1 <= tokens.get(self.token1).token_total, 'UniswapV3: M0' 
              
        return (amount0, amount1)
        

    def collect(self, recipient, tickLower, tickUpper, amount0Requested, amount1Requested):
        checkInputTypes(
            accounts=(recipient),
            int24=(tickLower, tickUpper),
            uint128=(amount0Requested, amount1Requested),
        )
        # Add this check to prevent creating a new position if the position doesn't exist or it's empty
        position = Position.assertPositionExists(
            self.positions, recipient, tickLower, tickUpper
        )

        amount0 = (
            position.tokensOwed0
            if (amount0Requested > position.tokensOwed0)
            else amount0Requested
        )
        amount1 = (
            position.tokensOwed1
            if (amount1Requested > position.tokensOwed1)
            else amount1Requested
        )

        if amount0 > 0:
            position.tokensOwed0 -= amount0
            #self.ledger.transferToken(self, recipient, self.token0, amount0)
        if amount1 > 0:
            position.tokensOwed1 -= amount1
            #self.ledger.transferToken(self, recipient, self.token1, amount1)

        return (recipient, tickLower, tickUpper, amount0, amount1)   
        

    def burn(self, recipient, tickLower, tickUpper, amount):

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        checkInputTypes(
            accounts=(recipient), int24=(tickLower, tickUpper), uint128=(amount)
        )

        # Add check if the position exists - when poking an uninitialized position it can be that
        # getFeeGrowthInside finds a non-initialized tick before Position.update reverts.
        Position.assertPositionExists(self.positions, recipient, tickLower, tickUpper)

        # Added extra recipient input variable to mimic msg.sender
        (position, amount0Int, amount1Int) = self._modifyPosition(
            ModifyPositionParams(recipient, tickLower, tickUpper, -amount)
        )

        tokens = self.factory.token_from_exchange[self.name]
        tokens.get(self.token0).transfer(recipient, amount0Int)
        tokens.get(self.token1).transfer(recipient, amount1Int)     

        balanceA = tokens.get(self.token0).token_total
        balanceB = tokens.get(self.token1).token_total

        self._update(balanceA, balanceB)        

        # Mimic conversion to uint256
        amount0 = abs(-amount0Int) & (2**256 - 1)
        amount1 = abs(-amount1Int) & (2**256 - 1)        

        if amount0 > 0 or amount1 > 0:
            position.tokensOwed0 += amount0
            position.tokensOwed1 += amount1

        return (recipient, tickLower, tickUpper, amount, amount0, amount1)

    def _getSqrtPriceLimitX96(self, inputToken):
        if inputToken == 'Token0':
            return 4295128739 + 1
        else:
            return 4295128739 - 1 

    def swapExact0For1(self, recipient, amount, sqrtPriceLimit):

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        sqrtPriceLimitX96 = (
            sqrtPriceLimit
            if sqrtPriceLimit != None
            else self._getSqrtPriceLimitX96('Token0')
        )
        #return swap(pool, TEST_TOKENS[0], [amount, 0], recipient, sqrtPriceLimitX96)
        return self._swap('Token0', [amount, 0], recipient, sqrtPriceLimitX96)  

    def swap0ForExact1(self, recipient,  amount, sqrtPriceLimit):

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        sqrtPriceLimitX96 = (
            sqrtPriceLimit
            if sqrtPriceLimit != None
            else self._getSqrtPriceLimitX96('Token0')
        )
        return self._swap('Token0', [0, amount], recipient, sqrtPriceLimitX96)  


    def swapExact1For0(self, recipient,  amount, sqrtPriceLimit):

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        sqrtPriceLimitX96 = (
            sqrtPriceLimit
            if sqrtPriceLimit != None
            else self._getSqrtPriceLimitX96('Token1')
        )
        return self._swap('Token1', [amount, 0], recipient, sqrtPriceLimitX96)
    
    def swap1ForExact0(self, recipient, amount, sqrtPriceLimit):

        amount = amount if self.precision == UniswapExchangeData.TYPE_GWEI else self.dec2gwei(amount)
        
        sqrtPriceLimitX96 = (
            sqrtPriceLimit
            if sqrtPriceLimit != None
            else self._getSqrtPriceLimitX96('Token1')
        )
        return self._swap('Token1', [0, amount], recipient, sqrtPriceLimitX96)     

        

    def _swap(self, inputToken, amounts, recipient, sqrtPriceLimitX96):
        [amountIn, amountOut] = amounts
        exactInput = amountOut == 0
        amount = amountIn if exactInput else amountOut

        if inputToken == 'Token0':
            if exactInput:
                checkInt128(amount)
                return self.swap(recipient, True, amount, sqrtPriceLimitX96)
            else:
                checkInt128(-amount)
                return self.swap(recipient, True, -amount, sqrtPriceLimitX96)
        else:
            if exactInput:
                checkInt128(amount)
                return self.swap(recipient, False, amount, sqrtPriceLimitX96)                  
            else:
                checkInt128(-amount)
                return self.swap(recipient, False, -amount, sqrtPriceLimitX96)      
    
    def swap(self, recipient, zeroForOne, amountSpecified, sqrtPriceLimitX96):
        checkInputTypes(
            accounts=(recipient),
            bool=(zeroForOne),
            int256=(amountSpecified),
            uint160=(sqrtPriceLimitX96),
        )
        assert amountSpecified != 0, "AS"

        slot0Start = self.slot0        
        
        if zeroForOne:
            assert (
                sqrtPriceLimitX96 < slot0Start.sqrtPriceX96
                and sqrtPriceLimitX96 > TickMath.MIN_SQRT_RATIO
            ), "SPL_"
        else:
            #x = sqrtPriceLimitX96 > slot0Start.sqrtPriceX96 and sqrtPriceLimitX96 < TickMath.MAX_SQRT_RATIO
            assert sqrtPriceLimitX96 < TickMath.MAX_SQRT_RATIO, "SPL"
            # assert (
            #    sqrtPriceLimitX96 > slot0Start.sqrtPriceX96
            #    and sqrtPriceLimitX96 < TickMath.MAX_SQRT_RATIO
            # ), "SPL"
  
        feeProtocol = (
            (slot0Start.feeProtocol % 16)
            if zeroForOne
            else (slot0Start.feeProtocol >> 4)
        )

        cache = SwapCache(feeProtocol, self.total_supply)

        exactInput = amountSpecified > 0

        state = SwapState(
            amountSpecified,
            0,
            slot0Start.sqrtPriceX96,
            slot0Start.tick,
            self.feeGrowthGlobal0X128 if zeroForOne else self.feeGrowthGlobal1X128,
            0,
            cache.liquidityStart,
            [],
        )

        while (
            state.amountSpecifiedRemaining != 0
            and state.sqrtPriceX96 != sqrtPriceLimitX96
        ):
            step = StepComputations(0, 0, 0, 0, 0, 0, 0)
            step.sqrtPriceStartX96 = state.sqrtPriceX96

            (step.tickNext, step.initialized) = self.nextTick(state.tick, zeroForOne)

            ## get the price for the next tick
            step.sqrtPriceNextX96 = TickMath.getSqrtRatioAtTick(step.tickNext)

            ## compute values to swap to the target tick, price limit, or point where input#output amount is exhausted
            if zeroForOne:
                sqrtRatioTargetX96 = (
                    sqrtPriceLimitX96
                    if step.sqrtPriceNextX96 < sqrtPriceLimitX96
                    else step.sqrtPriceNextX96
                )
            else:
                sqrtRatioTargetX96 = (
                    sqrtPriceLimitX96
                    if step.sqrtPriceNextX96 > sqrtPriceLimitX96
                    else step.sqrtPriceNextX96
                )

            (
                state.sqrtPriceX96,
                step.amountIn,
                step.amountOut,
                step.feeAmount,
            ) = SwapMath.computeSwapStep(
                state.sqrtPriceX96,
                sqrtRatioTargetX96,
                state.liquidity,
                state.amountSpecifiedRemaining,
                self.fee,
            )
            if exactInput:
                state.amountSpecifiedRemaining -= step.amountIn + step.feeAmount
                state.amountCalculated = SafeMath.subInts(
                    state.amountCalculated, step.amountOut
                )
            else:
                state.amountSpecifiedRemaining += step.amountOut
                state.amountCalculated = SafeMath.addInts(
                    state.amountCalculated, step.amountIn + step.feeAmount
                )

            ## if the protocol fee is on, calculate how much is owed, decrement feeAmount, and increment protocolFee
            if cache.feeProtocol > 0:
                delta = abs(step.feeAmount // cache.feeProtocol)
                step.feeAmount -= delta
                state.protocolFee += delta & (2**128 - 1)

            ## update global fee tracker
            if state.liquidity > 0:
                state.feeGrowthGlobalX128 += FullMath.mulDiv(
                    step.feeAmount, FixedPoint128_Q128, state.liquidity
                )
                # Addition can overflow in Solidity - mimic it
                state.feeGrowthGlobalX128 = toUint256(state.feeGrowthGlobalX128)

            ## shift tick if we reached the next price
            if state.sqrtPriceX96 == step.sqrtPriceNextX96:
                ## if the tick is initialized, run the tick transition
                ## @dev: here is where we should handle the case of an uninitialized boundary tick
                if step.initialized:
                    liquidityNet = Tick.cross(
                        self.ticks,
                        step.tickNext,
                        state.feeGrowthGlobalX128
                        if zeroForOne
                        else self.feeGrowthGlobal0X128,
                        self.feeGrowthGlobal1X128
                        if zeroForOne
                        else state.feeGrowthGlobalX128,
                    )
                    ## if we're moving leftward, we interpret liquidityNet as the opposite sign
                    ## safe because liquidityNet cannot be type(int128).min
                    if zeroForOne:
                        liquidityNet = -liquidityNet

                    state.liquidity = LiquidityMath.addDelta(
                        state.liquidity, liquidityNet
                    )

                state.tick = (step.tickNext - 1) if zeroForOne else step.tickNext
            elif state.sqrtPriceX96 != step.sqrtPriceStartX96:
                ## recompute unless we're on a lower tick boundary (i.e. already transitioned ticks), and haven't moved
                state.tick = TickMath.getTickAtSqrtRatio(state.sqrtPriceX96)

        ## End of swap loop
        ## update tick
        if state.tick != slot0Start.tick:
            self.slot0.sqrtPriceX96 = state.sqrtPriceX96
            self.slot0.tick = state.tick
        else:
            ## otherwise just update the price
            self.slot0.sqrtPriceX96 = state.sqrtPriceX96

        ## update liquidity if it changed
        if cache.liquidityStart != state.liquidity:
            self.liquidity = state.liquidity

        ## update fee growth global and, if necessary, protocol fees
        ## overflow is acceptable, protocol has to withdraw before it hits type(uint128).max fees

        if zeroForOne:
            self.feeGrowthGlobal0X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token0 += state.protocolFee
        else:
            self.feeGrowthGlobal1X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token1 += state.protocolFee

        (amount0, amount1) = (
            (amountSpecified - state.amountSpecifiedRemaining, state.amountCalculated)
            if (zeroForOne == exactInput)
            else (
                state.amountCalculated,
                amountSpecified - state.amountSpecifiedRemaining,
            )
        )

        #print(f'amount0 {self.gwei2dec(amount0)}')       
        #print(f'amount1 {self.gwei2dec(amount1)}')  
        
        tokens = self.factory.token_from_exchange[self.name]
        if zeroForOne: 
            tokens.get(self.token0).deposit(recipient, abs(amount0))
            self._swap_tokens(0, abs(amount1), recipient)            
        else: 
            tokens.get(self.token1).deposit(recipient, abs(amount1))
            self._swap_tokens(abs(amount0), 0, recipient)            
        
        #self._swap_tokens(amount0, amount1, recipient)
        ## do the transfers and collect payment
        ## if zeroForOne:
        ##    if amount1 < 0:
        ##        self.ledger.transferToken(self, recipient, self.token1, abs(amount1))
        ##    balanceBefore = self.balances[self.token0]
        ##    self.ledger.transferToken(recipient, self, self.token0, abs(amount0))
        ##    assert balanceBefore + abs(amount0) == self.balances[self.token0], "IIA"
        ##else:
        ##    if amount0 < 0:
        ##        self.ledger.transferToken(self, recipient, self.token0, abs(amount0))

        ##    balanceBefore = self.balances[self.token1]
        ##    self.ledger.transferToken(recipient, self, self.token1, abs(amount1))
        ##    assert balanceBefore + abs(amount1) == self.balances[self.token1], "IIA"    

        return (
            recipient,
            amount0,
            amount1,
            state.sqrtPriceX96,
            state.liquidity,
            state.tick,
        )

    def setFeeProtocol(self, feeProtocol0, feeProtocol1):
        checkInputTypes(uint8=(feeProtocol0, feeProtocol1))
        assert (feeProtocol0 == 0 or (feeProtocol0 >= 4 and feeProtocol0 <= 10)) and (
            feeProtocol1 == 0 or (feeProtocol1 >= 4 and feeProtocol1 <= 10)
        )

        feeProtocolOld = self.slot0.feeProtocol
        feeProtocolNew = feeProtocol0 + (feeProtocol1 << 4)
        # Health check
        checkUInt8(feeProtocolNew)
        self.slot0.feeProtocol = feeProtocolNew
        return (feeProtocolOld % 16, feeProtocolOld >> 4, feeProtocol0, feeProtocol1) 

    def _swap_tokens(self, amountA_out, amountB_out, to_addr):
        
        """ _swap_tokens

            Remove liquidity from both coins in the pair based on lp amount
                
            Parameters
            -----------------
            amountA_out : float
                swap amountA out
            amountB_out : float
                swap amountB out               
            to_addr : str
               receiving user address                   
        """         
        
        assert amountA_out > 0 or amountB_out > 0, 'UniswapV3: INSUFFICIENT_OUTPUT_AMOUNT'
        assert amountA_out < self.reserve0 and amountB_out < self.reserve1, 'UniswapV3: INSUFFICIENT_LIQUIDITY'

        tokens = self.factory.token_from_exchange[self.name]
        assert tokens.get(self.token0).token_addr != to_addr, 'UniswapV3: INVALID_TO_ADDRESS'
        assert tokens.get(self.token1).token_addr != to_addr, 'UniswapV3: INVALID_TO_ADDRESS'
        
        tokens.get(self.token0).transfer(to_addr, amountA_out)
        tokens.get(self.token1).transfer(to_addr, amountB_out)    
        
        balanceA = tokens.get(self.token0).token_total
        balanceB = tokens.get(self.token1).token_total

        amountA_in = balanceA - (self.reserve0 - amountA_out) if balanceA > self.reserve0 - amountA_out else 0
        amountB_in = balanceB - (self.reserve1 - amountB_out) if balanceB > self.reserve1 - amountB_out else 0

        assert amountA_in > 0 or amountB_in > 0, 'UniswapV3: INSUFFICIENT_INPUT_AMOUNT'
    
        self._update(balanceA, balanceB)    
    
    def get_price(self, token): 
        pass
            
    def get_reserve(self, token): 
        pass

    def _update(self, balanceA, balanceB):
        
        """ _update

            Update reserve amounts for both coins in the pair
                
            Parameters
            -----------------   
            balanceA : float
                new reserve amount of A      
            balance1 : float
                new reserve amount of B                   
        """         
        
        self.reserve0 = balanceA
        self.reserve1 = balanceB    
    
    def _modifyPosition(self, params):

        checkInputTypes(
            accounts=(params.owner),
            int24=(params.tickLower, params.tickUpper),
            int128=(params.liquidityDelta),
        )
        self.checkTicks(params.tickLower, params.tickUpper)

        # Initialize values
        amount0 = amount1 = 0

        position = self._updatePosition(
            params.owner,
            params.tickLower,
            params.tickUpper,
            params.liquidityDelta,
            self.slot0.tick,
        )

        if params.liquidityDelta != 0:
            if self.slot0.tick < params.tickLower:
                ## current tick is below the passed range; liquidity can only become in range by crossing from left to
                ## right, when we'll need _more_ token0 (it's becoming more valuable) so user must provide it
                amount0 = SqrtPriceMath.getAmount0DeltaHelper(
                    TickMath.getSqrtRatioAtTick(params.tickLower),
                    TickMath.getSqrtRatioAtTick(params.tickUpper),
                    params.liquidityDelta,
                )
            elif self.slot0.tick < params.tickUpper:
                ## current tick is inside the passed range
                amount0 = SqrtPriceMath.getAmount0DeltaHelper(
                    self.slot0.sqrtPriceX96,
                    TickMath.getSqrtRatioAtTick(params.tickUpper),
                    params.liquidityDelta,
                )
                amount1 = SqrtPriceMath.getAmount1DeltaHelper(
                    TickMath.getSqrtRatioAtTick(params.tickLower),
                    self.slot0.sqrtPriceX96,
                    params.liquidityDelta,
                )
                self.total_supply = LiquidityMath.addDelta(
                    self.total_supply, params.liquidityDelta
                )
            else:
                ## current tick is above the passed range; liquidity can only become in range by crossing from right to
                ## left, when we'll need _more_ token1 (it's becoming more valuable) so user must provide it
                amount1 = SqrtPriceMath.getAmount1DeltaHelper(
                    TickMath.getSqrtRatioAtTick(params.tickLower),
                    TickMath.getSqrtRatioAtTick(params.tickUpper),
                    params.liquidityDelta,
                )

        return (position, amount0, amount1)  
    
    def _updatePosition(self, owner, tickLower, tickUpper, liquidityDelta, tick):
        checkInputTypes(
            accounts=(owner),
            int24=(tickLower, tickUpper, tick),
            int128=(liquidityDelta),
        )
        # This will create a position if it doesn't exist

        
        position = Position.get(self.positions, owner, tickLower, tickUpper)

        # Initialize values
        flippedLower = flippedUpper = False

        ## if we need to update the ticks, do it
        if liquidityDelta != 0:
            flippedLower = Tick.update(
                self.ticks,
                tickLower,
                tick,
                liquidityDelta,
                self.feeGrowthGlobal0X128,
                self.feeGrowthGlobal1X128,
                False,
                self.maxLiquidityPerTick,
            )
            flippedUpper = Tick.update(
                self.ticks,
                tickUpper,
                tick,
                liquidityDelta,
                self.feeGrowthGlobal0X128,
                self.feeGrowthGlobal1X128,
                True,
                self.maxLiquidityPerTick,
            )

        if flippedLower:
            assert tickLower % self.tickSpacing == 0  ## ensure that the tick is spaced
        if flippedUpper:
            assert tickUpper % self.tickSpacing == 0  ## ensure that the tick is spaced

        (feeGrowthInside0X128, feeGrowthInside1X128) = Tick.getFeeGrowthInside(
            self.ticks,
            tickLower,
            tickUpper,
            tick,
            self.feeGrowthGlobal0X128,
            self.feeGrowthGlobal1X128,
        )

        Position.update(
            position, liquidityDelta, feeGrowthInside0X128, feeGrowthInside1X128
        )

        ## clear any tick data that is no longer needed
        if liquidityDelta < 0:
            if flippedLower:
                Tick.clear(self.ticks, tickLower)
            if flippedUpper:
                Tick.clear(self.ticks, tickUpper)
        return position    
    
    def nextTick(self, tick, lte):
        checkInputTypes(int24=(tick), bool=(lte))

        keyList = list(self.ticks.keys())

        # If tick doesn't exist in the mapping we fake it (easier than searching for nearest value). This is probably not the
        # best way, but it is a simple and intuitive way to reproduce the behaviour of the logic.
        if not self.ticks.__contains__(tick):
            keyList += [tick]
        sortedKeyList = sorted(keyList)
        indexCurrentTick = sortedKeyList.index(tick)

        if lte:
            # If the current tick is initialized (not faked), we return the current tick
            if self.ticks.__contains__(tick):
                return tick, True
            elif indexCurrentTick == 0:
                # No tick to the left
                return TickMath.MIN_TICK, False
            else:
                nextTick = sortedKeyList[indexCurrentTick - 1]
        else:

            if indexCurrentTick == len(sortedKeyList) - 1:
                # No tick to the right
                return TickMath.MAX_TICK, False
            nextTick = sortedKeyList[indexCurrentTick + 1]

        # Return tick within the boundaries
        return nextTick, True    