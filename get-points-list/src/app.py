import logging

from fis_points_download import fis_points_download 
from ussa_points_download import ussa_points_download


def lambda_handler(event=None, context=None):
	# set up logger
	logger = logging.getLogger()
	logger.setLevel(logging.INFO)

	fis_points_download(logger)
	ussa_points_download(logger)