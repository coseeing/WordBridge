from decimal import Decimal, localcontext, ROUND_DOWN
from functools import partial

def decimal_to_str(value: Decimal, min_decimal_places: int = None) -> str:
	"""
	Convert a Decimal to a non-scientific notation string, forcing a specific number of decimal places.
	"""
	if not isinstance(value, Decimal):
		raise TypeError("value must be of type Decimal")

	# Default fallback is 0
	digits = min_decimal_places or 0

	with localcontext() as ctx:
		ctx.prec = digits + 5  # Extra precision buffer for safety
		# Quantize to the specified decimal places (pads with zeros or trims excess digits)
		quantized = value.quantize(Decimal('1.' + '0' * digits), rounding=ROUND_DOWN)

	return format(quantized, 'f')


def decimal_to_str_0(value: Decimal) -> str:
	"""
	Convert a Decimal to a standard string without scientific notation, without forcing trailing zeros.
	Example: Decimal('5E-7') ➜ '0.0000005'
	"""
	if not isinstance(value, Decimal):
		raise TypeError("value must be of type Decimal")

	return format(value.normalize(), 'f').rstrip('0').rstrip('.') if '.' in str(value) else str(value)


decimal_to_str_10 = partial(decimal_to_str, min_decimal_places=10)
decimal_to_str_12 = partial(decimal_to_str, min_decimal_places=12)
