"""
Order execution module for Binance spot trading.
"""
import time
from typing import Dict, Optional
import logging

from data.binance_rest import BinanceRESTClient

logger = logging.getLogger(__name__)


class OrderExecutor:
    """
    Execute orders on Binance with proper error handling.
    
    Key rules:
    - Use LIMIT orders by default
    - Use MARKET orders ONLY on risk exits
    - Validate all parameters before execution
    - Never log sensitive data
    """
    
    def __init__(self, config: Dict, mode: str = 'paper'):
        self.mode = mode  # 'paper' or 'live'
        
        exec_config = config.get('execution', {})
        self.default_order_type = exec_config.get('default_order_type', 'LIMIT')
        self.use_market_on_risk_exit = exec_config.get('use_market_on_risk_exit', True)
        self.limit_order_timeout = exec_config.get('limit_order_timeout_seconds', 30)
        
        # Initialize Binance client
        base_url = exec_config.get('binance_base_url', 'https://api.binance.com')
        self.client = BinanceRESTClient(base_url=base_url)
        
        # Track paper trades
        self.paper_trades = []
    
    def execute_buy(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: Optional[str] = None,
        reason: str = ''
    ) -> Dict[str, any]:
        """
        Execute buy order.
        
        Args:
            symbol: Trading pair
            quantity: Quantity to buy
            price: Limit price (optional, required for LIMIT orders)
            order_type: Order type (LIMIT or MARKET)
            reason: Reason for trade (for logging)
        
        Returns:
            Order result dictionary
        """
        if order_type is None:
            order_type = self.default_order_type
        
        # Validate
        if quantity <= 0:
            return {
                'success': False,
                'error': 'Invalid quantity'
            }
        
        if order_type == 'LIMIT' and price is None:
            return {
                'success': False,
                'error': 'Price required for LIMIT order'
            }
        
        # Paper mode
        if self.mode == 'paper':
            return self._paper_buy(symbol, quantity, price, order_type, reason)
        
        # Live mode
        try:
            logger.info(f"Executing BUY: {symbol} qty={quantity:.6f} type={order_type} reason={reason}")
            
            result = self.client.place_order(
                symbol=symbol,
                side='BUY',
                order_type=order_type,
                quantity=quantity,
                price=price
            )
            
            if result:
                logger.info(f"BUY order executed: {symbol} orderId={result.get('orderId')}")
                return {
                    'success': True,
                    'order_id': result.get('orderId'),
                    'symbol': symbol,
                    'side': 'BUY',
                    'quantity': quantity,
                    'price': result.get('price', price),
                    'order_type': order_type,
                    'status': result.get('status'),
                    'reason': reason
                }
            else:
                logger.error(f"BUY order failed: {symbol}")
                return {
                    'success': False,
                    'error': 'Order execution failed'
                }
        
        except Exception as e:
            logger.error(f"Error executing BUY order: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def execute_sell(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: Optional[str] = None,
        reason: str = '',
        is_risk_exit: bool = False
    ) -> Dict[str, any]:
        """
        Execute sell order.
        
        Args:
            symbol: Trading pair
            quantity: Quantity to sell
            price: Limit price (optional)
            order_type: Order type
            reason: Reason for trade
            is_risk_exit: If True, use MARKET order (if configured)
        
        Returns:
            Order result dictionary
        """
        # Use MARKET order for risk exits if configured
        if is_risk_exit and self.use_market_on_risk_exit:
            order_type = 'MARKET'
            price = None
        elif order_type is None:
            order_type = self.default_order_type
        
        # Validate
        if quantity <= 0:
            return {
                'success': False,
                'error': 'Invalid quantity'
            }
        
        if order_type == 'LIMIT' and price is None:
            return {
                'success': False,
                'error': 'Price required for LIMIT order'
            }
        
        # Paper mode
        if self.mode == 'paper':
            return self._paper_sell(symbol, quantity, price, order_type, reason)
        
        # Live mode
        try:
            logger.info(f"Executing SELL: {symbol} qty={quantity:.6f} type={order_type} reason={reason}")
            
            result = self.client.place_order(
                symbol=symbol,
                side='SELL',
                order_type=order_type,
                quantity=quantity,
                price=price
            )
            
            if result:
                logger.info(f"SELL order executed: {symbol} orderId={result.get('orderId')}")
                return {
                    'success': True,
                    'order_id': result.get('orderId'),
                    'symbol': symbol,
                    'side': 'SELL',
                    'quantity': quantity,
                    'price': result.get('price', price),
                    'order_type': order_type,
                    'status': result.get('status'),
                    'reason': reason
                }
            else:
                logger.error(f"SELL order failed: {symbol}")
                return {
                    'success': False,
                    'error': 'Order execution failed'
                }
        
        except Exception as e:
            logger.error(f"Error executing SELL order: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _paper_buy(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float],
        order_type: str,
        reason: str
    ) -> Dict[str, any]:
        """Execute paper buy (simulation)."""
        order_id = f"PAPER_{int(time.time() * 1000)}"
        
        trade = {
            'success': True,
            'order_id': order_id,
            'symbol': symbol,
            'side': 'BUY',
            'quantity': quantity,
            'price': price,
            'order_type': order_type,
            'status': 'FILLED',
            'reason': reason,
            'timestamp': time.time(),
            'mode': 'paper'
        }
        
        self.paper_trades.append(trade)
        logger.info(f"[PAPER] BUY: {symbol} qty={quantity:.6f} price={price} reason={reason}")
        
        return trade
    
    def _paper_sell(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float],
        order_type: str,
        reason: str
    ) -> Dict[str, any]:
        """Execute paper sell (simulation)."""
        order_id = f"PAPER_{int(time.time() * 1000)}"
        
        trade = {
            'success': True,
            'order_id': order_id,
            'symbol': symbol,
            'side': 'SELL',
            'quantity': quantity,
            'price': price,
            'order_type': order_type,
            'status': 'FILLED',
            'reason': reason,
            'timestamp': time.time(),
            'mode': 'paper'
        }
        
        self.paper_trades.append(trade)
        logger.info(f"[PAPER] SELL: {symbol} qty={quantity:.6f} price={price} reason={reason}")
        
        return trade
    
    def get_paper_trades(self) -> list:
        """Get all paper trades."""
        return self.paper_trades
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, any]:
        """
        Cancel an order.
        
        Args:
            symbol: Trading pair
            order_id: Order ID to cancel
        
        Returns:
            Cancel result
        """
        if self.mode == 'paper':
            logger.info(f"[PAPER] Cancel order: {symbol} orderId={order_id}")
            return {'success': True, 'mode': 'paper'}
        
        try:
            result = self.client.cancel_order(symbol, order_id)
            if result:
                logger.info(f"Order canceled: {symbol} orderId={order_id}")
                return {'success': True, 'result': result}
            else:
                return {'success': False, 'error': 'Cancel failed'}
        except Exception as e:
            logger.error(f"Error canceling order: {e}")
            return {'success': False, 'error': str(e)}
