import numpy as np
from .coefficient_set import CoefficientSet
from .helper_functions import print_log

def setup_loss_functions(data, coef_set, L0_max = None, loss_computation = None, w_pos = 1.0):
    """

    Parameters
    ----------
    data
    coef_set
    L0_max
    loss_computation
    w_pos

    Returns
    -------

    """
    #todo check if fast/lookup loss is installed
    assert loss_computation in [None, 'weighted', 'normal', 'fast', 'lookup']
    MAX_DISTINCT_XY_VALUES_FOR_LOOKUP_ON_NONINTEGER_DATA = 20

    Z = data['X'] * data['Y']

    if 'sample_weights' in data:
        sample_weights = _setup_training_weights(Y = data['Y'], sample_weights = data['sample_weights'], w_pos = w_pos)
        use_weighted = not np.all(np.equal(sample_weights, 1.0))
    else:
        use_weighted = False

    integer_data_flag = np.all(Z == np.require(Z, dtype = np.int_))
    distinct_points_flag = len(np.unique(Z, axis = 0)) <= MAX_DISTINCT_XY_VALUES_FOR_LOOKUP_ON_NONINTEGER_DATA
    use_lookup_table = isinstance(coef_set, CoefficientSet) and (integer_data_flag or distinct_points_flag)
    if use_weighted:
        final_loss_computation = 'weighted'
    elif use_lookup_table:
        final_loss_computation = 'lookup'
    else:
        final_loss_computation = 'fast'

    if final_loss_computation != loss_computation:
        print_log("switching loss computation from %s to %s" % (loss_computation, final_loss_computation))

    if final_loss_computation == 'weighted':

        from riskslim.loss_functions.log_loss_weighted import \
            log_loss_value, \
            log_loss_value_and_slope, \
            log_loss_value_from_scores

        Z = np.require(Z, requirements = ['C'])
        total_sample_weights = np.sum(sample_weights)

        compute_loss = lambda rho: log_loss_value(Z, sample_weights, total_sample_weights, rho)
        compute_loss_cut = lambda rho: log_loss_value_and_slope(Z, sample_weights, total_sample_weights, rho)
        compute_loss_from_scores = lambda scores: log_loss_value_from_scores(sample_weights, total_sample_weights, scores)

    elif final_loss_computation == 'normal':

        from riskslim.loss_functions.log_loss import \
            log_loss_value, \
            log_loss_value_and_slope, \
            log_loss_value_from_scores

        Z = np.require(Z, requirements=['C'])
        compute_loss = lambda rho: log_loss_value(Z, rho)
        compute_loss_cut = lambda rho: log_loss_value_and_slope(Z, rho)
        compute_loss_from_scores = lambda scores: log_loss_value_from_scores(scores)

    elif final_loss_computation == 'fast':

        from riskslim.loss_functions.fast_log_loss import \
            log_loss_value, \
            log_loss_value_and_slope, \
            log_loss_value_from_scores

        Z = np.require(Z, requirements=['F'])
        compute_loss = lambda rho: log_loss_value(Z, rho)
        compute_loss_cut = lambda rho: log_loss_value_and_slope(Z, rho)
        compute_loss_from_scores = lambda scores: log_loss_value_from_scores(scores)

    elif final_loss_computation == 'lookup':

        from riskslim.loss_functions.lookup_log_loss import \
            get_loss_value_and_prob_tables, \
            log_loss_value, \
            log_loss_value_and_slope, \
            log_loss_value_from_scores

        s_min, s_max = get_score_bounds(Z_min = np.min(Z, axis=0),
                                        Z_max = np.max(Z, axis=0),
                                        rho_lb = coef_set.lb,
                                        rho_ub = coef_set.ub,
                                        L0_reg_ind = np.array(coef_set.c0) == 0.0,
                                        L0_max = L0_max)


        Z = np.require(Z, requirements=['F'], dtype = np.float)
        print_log("%d rows in lookup table" % (s_max - s_min + 1))

        loss_value_tbl, prob_value_tbl, tbl_offset = get_loss_value_and_prob_tables(s_min, s_max)
        compute_loss = lambda rho: log_loss_value(Z, rho, loss_value_tbl, tbl_offset)
        compute_loss_cut = lambda rho: log_loss_value_and_slope(Z, rho, loss_value_tbl, prob_value_tbl, tbl_offset)
        compute_loss_from_scores = lambda scores: log_loss_value_from_scores(scores, loss_value_tbl, tbl_offset)

    # real loss functions
    if final_loss_computation == 'lookup':

        from riskslim.loss_functions.fast_log_loss import \
            log_loss_value as loss_value_real, \
            log_loss_value_and_slope as loss_value_and_slope_real,\
            log_loss_value_from_scores as loss_value_from_scores_real

        compute_loss_real = lambda rho: loss_value_real(Z, rho)
        compute_loss_cut_real = lambda rho: loss_value_and_slope_real(Z, rho)
        compute_loss_from_scores_real = lambda scores: loss_value_from_scores_real(scores)

    else:

        compute_loss_real = compute_loss
        compute_loss_cut_real = compute_loss_cut
        compute_loss_from_scores_real = compute_loss_from_scores

    return (Z,
            compute_loss,
            compute_loss_cut,
            compute_loss_from_scores,
            compute_loss_real,
            compute_loss_cut_real,
            compute_loss_from_scores_real)


def _setup_training_weights(Y, sample_weights = None, w_pos = 1.0, w_neg = 1.0, w_total_target = 2.0):

    """
    Parameters
    ----------
    Y - N x 1 vector with Y = -1,+1
    sample_weights - N x 1 vector
    w_pos - positive scalar showing relative weight on examples where Y = +1
    w_neg - positive scalar showing relative weight on examples where Y = -1

    Returns
    -------
    a vector of N training weights for all points in the training data

    """

    # todo: throw warning if there is no positive/negative point in Y

    # process class weights
    assert w_pos > 0.0, 'w_pos must be strictly positive'
    assert w_neg > 0.0, 'w_neg must be strictly positive'
    assert np.isfinite(w_pos), 'w_pos must be finite'
    assert np.isfinite(w_neg), 'w_neg must be finite'
    w_total = w_pos + w_neg
    w_pos = w_total_target * (w_pos / w_total)
    w_neg = w_total_target * (w_neg / w_total)

    # process case weights
    Y = Y.flatten()
    N = len(Y)
    pos_ind = Y == 1

    if sample_weights is None:
        training_weights = np.ones(N)
    else:
        training_weights = sample_weights.flatten()
        assert len(training_weights) == N
        assert np.all(training_weights >= 0.0)
        #todo: throw warning if any training weights = 0
        #todo: throw warning if there are no effective positive/negative points in Y

    # normalization
    training_weights = N * (training_weights / sum(training_weights))
    training_weights[pos_ind] *= w_pos
    training_weights[~pos_ind] *= w_neg

    return training_weights


def setup_penalty_parameters(coef_set, c0_value = 1e-6):
    """

    Parameters
    ----------
    coef_set
    c0_value

    Returns
    -------
    c0_value
    C_0
    L0_reg_ind
    C_0_nnz
    """
    assert isinstance(coef_set, CoefficientSet)
    assert c0_value > 0.0, 'default L0_parameter should be positive'
    c0_value = float(c0_value)
    C_0 = np.array(coef_set.c0)
    L0_reg_ind = np.isnan(C_0)
    C_0[L0_reg_ind] = c0_value
    C_0_nnz = C_0[L0_reg_ind]
    return c0_value, C_0, L0_reg_ind, C_0_nnz


def setup_objective_functions(compute_loss, L0_reg_ind, C_0_nnz):

    get_objval = lambda rho: compute_loss(rho) + np.sum(C_0_nnz * (rho[L0_reg_ind] != 0.0))
    get_L0_norm = lambda rho: np.count_nonzero(rho[L0_reg_ind])
    get_L0_penalty = lambda rho: np.sum(C_0_nnz * (rho[L0_reg_ind] != 0.0))
    get_alpha = lambda rho: np.array(abs(rho[L0_reg_ind]) > 0.0, dtype = np.float_)
    get_L0_penalty_from_alpha = lambda alpha: np.sum(C_0_nnz * alpha)

    return (get_objval, get_L0_norm, get_L0_penalty, get_alpha, get_L0_penalty_from_alpha)


def get_conservative_offset(data, coef_set, max_L0_value = None):
    """
    returns a value of the offset that is guaranteed to avoid a loss in performance due to small values. this value is
    overly conservative.

    Parameters
    ----------
    data
    coef_set
    max_L0_value

    Returns
    -------
    optimal_offset = max_abs_score + 1
    where max_abs_score is the largest absolute score that can be achieved using the coefficients in coef_set
    with the training data. note:
    when offset >= optimal_offset, then we predict y = +1 for every example
    when offset <= optimal_offset, then we predict y = -1 for every example
    thus, any feasible model should do better.

    """
    if '(Intercept)' not in coef_set.variable_names:
        raise ValueError("coef_set must contain a variable for the offset called '(Intercept)'")

    # get idx of intercept/variables
    variable_idx = list(range(len(coef_set)))
    variable_idx.remove(coef_set.variable_names.index('(Intercept)'))
    variable_idx = np.array(variable_idx)

    # get max # of non-zero coefficients given model size limit
    L0_reg_ind = np.isnan(coef_set.C_0j)[variable_idx]
    trivial_L0_max = np.sum(L0_reg_ind)
    if max_L0_value is not None and max_L0_value > 0:
        max_L0_value = min(trivial_L0_max, max_L0_value)
    else:
        max_L0_value = trivial_L0_max

    Z = data['X'] * data['Y']
    Z_min = np.min(Z, axis = 0)
    Z_max = np.max(Z, axis = 0)

    # get smallest / largest score
    s_min, s_max = get_score_bounds(Z_min = Z_min[variable_idx],
                                    Z_max = Z_max[variable_idx],
                                    rho_lb = coef_set.lb[variable_idx],
                                    rho_ub = coef_set.ub[variable_idx],
                                    L0_reg_ind = L0_reg_ind,
                                    L0_max = max_L0_value)

    # get max # of non-zero coefficients given model size limit
    conservative_offset = max(abs(s_min), abs(s_max)) + 1
    return conservative_offset


def get_score_bounds(Z_min, Z_max, rho_lb, rho_ub, L0_reg_ind = None, L0_max = None):

    edge_values = np.vstack([Z_min * rho_lb, Z_max * rho_lb, Z_min * rho_ub, Z_max * rho_ub])

    if (L0_max is None) or (L0_reg_ind is None) or (L0_max == Z_min.shape[0]):
        s_min = np.sum(np.min(edge_values, axis=0))
        s_max = np.sum(np.max(edge_values, axis=0))
    else:
        min_values = np.min(edge_values, axis=0)
        s_min_reg = np.sum(np.sort(min_values[L0_reg_ind])[0:L0_max])
        s_min_no_reg = np.sum(min_values[~L0_reg_ind])
        s_min = s_min_reg + s_min_no_reg

        max_values = np.max(edge_values, axis=0)
        s_max_reg = np.sum(-np.sort(-max_values[L0_reg_ind])[0:L0_max])
        s_max_no_reg = np.sum(max_values[~L0_reg_ind])
        s_max = s_max_reg + s_max_no_reg

    return s_min, s_max


def get_loss_bounds(Z, rho_ub, rho_lb, L0_reg_ind, L0_max = float('nan')):
    # min value of loss = log(1+exp(-score)) occurs at max score for each point
    # max value of loss = loss(1+exp(-score)) occurs at min score for each point

    rho_lb = np.array(rho_lb)
    rho_ub = np.array(rho_ub)

    # get maximum number of regularized coefficients
    L0_max = Z.shape[0] if np.isnan(L0_max) else L0_max
    num_max_reg_coefs = min(L0_max, sum(L0_reg_ind))

    # calculate the smallest and largest score that can be attained by each point
    scores_at_lb = Z * rho_lb
    scores_at_ub = Z * rho_ub
    max_scores_matrix = np.maximum(scores_at_ub, scores_at_lb)
    min_scores_matrix = np.minimum(scores_at_ub, scores_at_lb)
    assert (np.all(max_scores_matrix >= min_scores_matrix))

    # for each example, compute max sum of scores from top reg coefficients
    max_scores_reg = max_scores_matrix[:, L0_reg_ind]
    max_scores_reg = -np.sort(-max_scores_reg, axis=1)
    max_scores_reg = max_scores_reg[:, 0:num_max_reg_coefs]
    max_score_reg = np.sum(max_scores_reg, axis=1)

    # for each example, compute max sum of scores from no reg coefficients
    max_scores_no_reg = max_scores_matrix[:, ~L0_reg_ind]
    max_score_no_reg = np.sum(max_scores_no_reg, axis=1)

    # max score for each example
    max_score = max_score_reg + max_score_no_reg

    # for each example, compute min sum of scores from top reg coefficients
    min_scores_reg = min_scores_matrix[:, L0_reg_ind]
    min_scores_reg = np.sort(min_scores_reg, axis=1)
    min_scores_reg = min_scores_reg[:, 0:num_max_reg_coefs]
    min_score_reg = np.sum(min_scores_reg, axis=1)

    # for each example, compute min sum of scores from no reg coefficients
    min_scores_no_reg = min_scores_matrix[:, ~L0_reg_ind]
    min_score_no_reg = np.sum(min_scores_no_reg, axis=1)

    min_score = min_score_reg + min_score_no_reg
    assert (np.all(max_score >= min_score))

    # compute min loss
    idx = max_score > 0
    min_loss = np.empty_like(max_score)
    min_loss[idx] = np.log1p(np.exp(-max_score[idx]))
    min_loss[~idx] = np.log1p(np.exp(max_score[~idx])) - max_score[~idx]
    min_loss = min_loss.mean()

    # compute max loss
    idx = min_score > 0
    max_loss = np.empty_like(min_score)
    max_loss[idx] = np.log1p(np.exp(-min_score[idx]))
    max_loss[~idx] = np.log1p(np.exp(min_score[~idx])) - min_score[~idx]
    max_loss = max_loss.mean()

    return min_loss, max_loss
