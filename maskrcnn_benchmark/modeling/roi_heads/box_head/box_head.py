# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
import torch
from torch import nn

from .roi_box_feature_extractors import make_roi_box_feature_extractor
from .roi_box_predictors import make_roi_box_predictor
from .inference import make_roi_box_post_processor
from .loss import make_roi_box_loss_evaluator


class ROIBoxHead(torch.nn.Module):
    """
    Generic Box Head class.
    """

    def __init__(self, cfg):
        super(ROIBoxHead, self).__init__()
        self.feature_extractor = make_roi_box_feature_extractor(cfg)
        self.predictor = make_roi_box_predictor(cfg)
        if cfg.MODEL.ROI_HEADS.TWO_BRANCH:
            self.feature_extractor_2nd = make_roi_box_feature_extractor(cfg)
            self.predictor_2nd = make_roi_box_predictor(cfg, is_2nd=True)
            self.loss_evaluator_2nd = make_roi_box_loss_evaluator(cfg)
        self.two_branch = cfg.MODEL.ROI_HEADS.TWO_BRANCH
        self.post_processor = make_roi_box_post_processor(cfg)
        self.loss_evaluator = make_roi_box_loss_evaluator(cfg)
        self.clsnet_inds_ = None

    def forward(self, features, proposals, targets=None):
        """
        Arguments:
            features (list[Tensor]): feature-maps from possibly several levels
            proposals (list[BoxList]): proposal boxes
            targets (list[BoxList], optional): the ground-truth targets.

        Returns:
            x (Tensor): the result of the feature extractor
            proposals (list[BoxList]): during training, the subsampled proposals
                are returned. During testing, the predicted boxlists are returned
            losses (dict[Tensor]): During training, returns the losses for the
                head. During testing, returns an empty dict.
        """

        if self.training:
            # Faster R-CNN subsamples during training the proposals with a fixed
            # positive / negative ratio
            with torch.no_grad():
                proposals = self.loss_evaluator.subsample(proposals, targets)
                if self.two_branch:
                    proposals_2nd = self.loss_evaluator_2nd.subsample(proposals, targets)

        # extract features that will be fed to the final classifier. The
        # feature_extractor generally corresponds to the pooler + heads
        x = self.feature_extractor(features, proposals)
        # final classifier that converts the features into predictions
        class_logits, box_regression, reconst_loss = self.predictor(x, clsnet_inds=self.clsnet_inds_)
        if not self.training and self.two_branch and self.clsnet_inds_ is None:
            x_2nd = self.feature_extractor_2nd(features, proposals)
            class_logits, box_regression = self.predictor_2nd(x_2nd)

        if not self.training:
            result = self.post_processor((class_logits, box_regression), proposals)
            return x, result, {}

        if self.two_branch:
            x_2nd = self.feature_extractor_2nd(features, proposals_2nd)
            class_logits_2nd, box_regression_2nd = self.predictor_2nd(x_2nd)
            loss_classifier_2nd, loss_box_reg_2nd = self.loss_evaluator_2nd(
                [class_logits_2nd], [box_regression_2nd]
            )

        loss_classifier, loss_box_reg = self.loss_evaluator(
            [class_logits], [box_regression]
        )
        if self.two_branch:
            return (
                x,
                proposals,
                dict(loss_classifier=loss_classifier, loss_box_reg=loss_box_reg,
                    loss_classifier_2nd=loss_classifier_2nd, loss_box_reg_2nd=loss_box_reg_2nd,
                    reconst_loss=reconst_loss),
            )
        else:
            return (
                x,
                proposals,
                dict(loss_classifier=loss_classifier, loss_box_reg=loss_box_reg,
                    reconst_loss=reconst_loss),
            )


def build_roi_box_head(cfg):
    """
    Constructs a new box head.
    By default, uses ROIBoxHead, but if it turns out not to be enough, just register a new class
    and make it a parameter in the config
    """
    return ROIBoxHead(cfg)
