"""
Lag-time helpers for multihit DEFORM simulations.

Lag time between hits gives the JMAK model time to evolve the microstructure
before the next deformation stroke. During lag, the model can use a larger time
step to reduce runtime; during the hit, it switches back to the smaller forming
time step.
"""


def build_lag_stroke_plan(
    previous_end_time,
    lag_time,
    move_dist,
    speed,
    hit_time_step,
    lag_time_step,
):
    """Build timing values for a lag period followed by a down-up-stop stroke."""
    if lag_time < 0:
        raise ValueError("lag_time must be zero or greater.")
    if move_dist <= 0:
        raise ValueError("move_dist must be greater than 0.")
    if speed <= 0:
        raise ValueError("speed must be greater than 0.")
    if hit_time_step <= 0:
        raise ValueError("hit_time_step must be greater than 0.")
    if lag_time_step <= 0:
        raise ValueError("lag_time_step must be greater than 0.")

    lag_start = previous_end_time
    lag_end = lag_start + lag_time
    stroke_start = lag_end + hit_time_step
    move_time = move_dist / speed
    stroke_down_end = stroke_start + move_time
    mid_change = stroke_down_end + hit_time_step
    stroke_up_start = stroke_down_end + 2 * hit_time_step
    stroke_up_end = stroke_up_start + move_time
    stroke_end_lag = stroke_up_end + hit_time_step
    stroke_end = stroke_end_lag + hit_time_step

    lag_steps = int((lag_end - lag_start) / lag_time_step) if lag_time > 0 else 0
    hit_steps = int((stroke_end - stroke_start) / hit_time_step)

    return {
        "lag_start": lag_start,
        "lag_end": lag_end,
        "stroke_start": stroke_start,
        "stroke_down_end": stroke_down_end,
        "mid_change": mid_change,
        "stroke_up_start": stroke_up_start,
        "stroke_up_end": stroke_up_end,
        "stroke_end_lag": stroke_end_lag,
        "stroke_end": stroke_end,
        "move_time": move_time,
        "lag_steps": lag_steps,
        "hit_steps": hit_steps,
        "total_steps": lag_steps + hit_steps,
    }


def create_dttype_key_string(plan, hit_time_step, lag_time_step):
    """Create a DEFORM `DTTYPE` block for coarse lag and fine hit time steps."""
    return f"""DTTYPE       3       4
        {plan["lag_start"]:.6E}    {lag_time_step:.6E}
        {plan["lag_end"]:.6E}    {lag_time_step:.6E}
        {plan["stroke_start"]:.6E}    {hit_time_step:.6E}
        {plan["stroke_end"]:.6E}    {hit_time_step:.6E}"""


def create_top_die_lag_movctl(plan, speed):
    """Create top-die MOVCTL for lag, downstroke, upstroke, and stop."""
    return f"""MOVCTL       2       1       2    0.0000000000E+000    0.0000000000E+000   -1.0000000000E+000       9
        {plan["lag_start"]:.6E}    0.0000000000E+000
        {plan["lag_end"]:.6E}    0.0000000000E+000
        {plan["stroke_start"]:.6E}    {speed:.6E}
        {plan["stroke_down_end"]:.6E}    {speed:.6E}
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start"]:.6E}    -{speed:.6E}
        {plan["stroke_up_end"]:.6E}    -{speed:.6E}
        {plan["stroke_end_lag"]:.6E}    0.0000000000E+000
        {plan["stroke_end"]:.6E}    0.0000000000E+000
        """


def create_bottom_die_lag_movctl(plan, speed, symmetric=False):
    """Create bottom-die MOVCTL for lag runs.

    If `symmetric` is False, the bottom die stays fixed during the downstroke
    and retracts during the upstroke, matching the older JMAK lag script. If
    True, bottom motion mirrors top motion for anti-bending behavior.
    """
    if symmetric:
        down_speed = -speed
        up_speed = speed
        down_start_speed = down_speed
        down_end_speed = down_speed
    else:
        up_speed = speed
        down_start_speed = 0.0
        down_end_speed = 0.0

    return f"""MOVCTL       3       1       2    0.0000000000E+000    0.0000000000E+000   -1.0000000000E+000       9
        {plan["lag_start"]:.6E}    0.0000000000E+000
        {plan["lag_end"]:.6E}    0.0000000000E+000
        {plan["stroke_start"]:.6E}    {down_start_speed:.6E}
        {plan["stroke_down_end"]:.6E}    {down_end_speed:.6E}
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start"]:.6E}    {up_speed:.6E}
        {plan["stroke_up_end"]:.6E}    {up_speed:.6E}
        {plan["stroke_end_lag"]:.6E}    0.0000000000E+000
        {plan["stroke_end"]:.6E}    0.0000000000E+000
        """


def apply_lag_time_controls(def_model, plan, save_step_size, hit_time_step, lag_time_step):
    """Apply DEFORM simulation step settings and adaptive `DTTYPE` for the plan."""
    def_model.simCtrl.setStepSettings(
        f'NSTART=-1, NSTEP={plan["total_steps"]}, STPINC={save_step_size}, DTMAX={lag_time_step}'
    )
    def_model.importKeyString(create_dttype_key_string(plan, hit_time_step, lag_time_step))


