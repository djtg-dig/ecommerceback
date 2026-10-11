import logging
import re


_CARRI_AUTH_QUERY = re.compile(r"(/api/v1/auth/carri/[^\s?\"']*)\?[^\s\"']*")


class OAuthQueryStringRedactionFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = _CARRI_AUTH_QUERY.sub(r"\1", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True