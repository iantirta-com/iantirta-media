
import os
from datetime import timezone, timedelta

from iantirta.media.worker.worker_mixin import GPUWorker

__all__ = [
    "KaggleWorker"
]


class KaggleWorker(GPUWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        os.environ["KAGGLE_API_TOKEN"] = self.access_token

        from kaggle import api
        self._api = api

    def get_quota(self) -> dict:
        quotas = self._api.quota_view()

        refresh_time = quotas.quota_refresh_time
        if refresh_time is not None and refresh_time.utcoffset() is None:
            # The SDK returns UTC timestamps without timezone information.
            refresh_time = refresh_time.replace(tzinfo=timezone.utc)
        
        quotas_per_type = [
            {
                "gpu": {
                    "time_used": quotas.gpu_quota.time_used, # timedelta
                    "time_allowed": quotas.gpu_quota.total_time_allowed # timedelta
                }
            },
            {
                "tpu": {
                    "time_used": quotas.tpu_quota.time_used,
                    "time_allowed": quotas.tpu_quota.total_time_allowed
                }
            }
        ]
        return {
            "refresh_time": refresh_time, # Datetime
            "types": quotas_per_type
        }

    def run(self, folder: str, **kwargs):
        """ Run kaggle kernel instance and push the notebook.
        
            :param str folder: the folder path containing
                               both .ipynb and kernel-metadata.json.
        """
        if not folder:
            raise RuntimeError("folder containing metadata and notebook need to be specified")
        result = self._api.kernels_push(
            folder=folder,
            timeout=None,
            acc=""
        )
        if result is None:
            raise RuntimeError("Kaggle push error, no definite data, see previous output.")
        elif not result.error:
            if result.invalidTags:
                raise RuntimeError(
                    "The following are not valid tags and could not be added "
                    "to the kernel: " + str(result.invalidTags)
                )
            if result.invalidDatasetSources:
                raise RuntimeError(
                    "The following are not valid dataset sources and could not "
                    "be added to the kernel: " + str(result.invalidDatasetSources)
                )
            if result.invalidCompetitionSources:
                raise RuntimeError(
                    "The following are not valid competition sources and could "
                    "not be added to the kernel: " + str(result.invalidCompetitionSources)
                )
            if result.invalidKernelSources:
                raise RuntimeError(
                    "The following are not valid kernel sources and could not "
                    "be added to the kernel: " + str(result.invalidKernelSources)
                )
            return result
        else:
            raise RuntimeError(f"Kaggle push error: {result.error}")


if __name__ == '__main__':
    api = KaggleWorker(access_token=os.environ['KAGGLE_API_TOKEN'])
    from pprint import pprint
    pprint(api.get_quota())