from typing import OrderedDict
from rest_framework.exceptions import ValidationError


class RequiredOrganizationIDMixin:
	required_url_kwargs = "org_id"

	def get_org_id(self):
		org_id = self.request.query_params.get(self.required_url_kwargs)
		if not org_id:
			raise ValidationError({
				self.required_url_kwargs: "The parameter is required"
			})
		return org_id