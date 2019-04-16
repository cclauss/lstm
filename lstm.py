import numpy as np

from functions import (L2_loss, d_sigmoid, d_tanh, sigmoid,
                       tanh, xavier_init, Dense)

class LSTM:
    """Class for LSTM network.
    
    Inputs:
        hidden_dim: size of the hidden layer, passed to the LSTM cell
        x_dim: size of network inputs (data passed to the network)
        loss: loss class, consisting of a loss function (loss) and it's derivative 
            w.r.t. prediction (dloss) as class methods. For an example, see functions.py
        init: initialization function, should take two dimensions x and y (integers) 
            as input and return an array of shape x, y. Passed to the LSTM cell.
        peephole: whether to use a peephole connection, boolean. Passed to the LSTM cell.
    """
    def __init__(self, hidden_dim, x_dim, learning_rate=1e-4, output_dim=1, 
                       loss=L2_loss, activation=Dense, init=xavier_init, peephole=True):
        self.cell = LSTM_unit(hidden_dim, x_dim, init=init, peephole=peephole, learning_rate=learning_rate)
        self.learning_rate = learning_rate
        self.loss = loss.loss
        self.dloss = loss.dloss
        self.activation = activation(hidden_dim, output_dim, learning_rate=learning_rate)

    def forward(self, x, y, a_prev=None, c_prev=None):
        """Forward prop.
        Inputs:
            x: Input array to network. Shape (time_steps, batch_size, x_dim)
            y: Post-activation target variables. Shape (time_steps, batch_size, output_dim)
            a_prev: Previous cell (pre-post-cell) activation. If None, will be initialized in cell.
            c_prev: Previous cell state. If None, will be initialized in cell.
        """
        states, caches, preds = [], [], []
        x = [x[t,:,:] for t in range(x.shape[0])]
        y = [y[t,:,:] for t in range(y.shape[0])]
        for xt, yt in zip(x, y):
            state, cache = self.cell.forward(xt, a_prev, c_prev)
            states.append(state)
            caches.append(cache)
            pred = self.activation.forward(state['a_out'])
            preds.append(pred.T)
            a_prev, c_prev = state['a_out'], state['c_out']
        return states, caches, np.stack(preds), np.stack(y)

    def backward(self, states, caches, preds, targets):
        """Backprop.
        Inputs:
            states: list of dictionaries containing states from LSTM_unit
            caches: TODO what do I even need these for
            preds: list of predictions (y_hat) of shape (output_dim, batch_size) #TODO check if it's batch_size, output_dim after all I'm too tired
            targets: list of labels with the same shape as preds
        """
        d_loss = np.mean(self.dloss(preds, targets), axis=0).T
        da_next = self.activation.backward(d_loss.T).T
        dc_next = np.zeros_like((states[0]['c_out']))
        grads = self.cell.init_grads()
        for state in reversed(states):
            da_next, dc_next, grad_adds = self.cell.backward(state, da_next, dc_next)
            for gate in ['c', 'u', 'o', 'f']:
                grads[gate]['w'] += grad_adds[gate]['w']
                grads[gate]['b'] += grad_adds[gate]['b']
        self.cell.update_params(grads)
        self.activation.update_params()
        return preds, targets
        
    def epoch(self, x, targets, a_prev=None, c_prev=None):
        preds, targets = self.backward(*self.forward(x, targets, a_prev=a_prev, c_prev=c_prev))
        return np.stack([self.loss(pred, yt) for pred, yt in zip(preds, targets)])

class LSTM_unit:
    """Class for LSTM cell.
    Inputs:
        hidden_dim: Size of the hidden layer
        x_dim: Size of network inputs
        init: Initialization function, should take a (two) tuple of integers x and y 
            as input and return an array of shape (x, y)
        grad_clip: Gradients will be clipped between -value and value. Pass None to disable clipping 
        peephole: Whether to use a peephole connection, boolean
    """
    def __init__(self, hidden_dim, x_dim, init=xavier_init, grad_clip=1, peephole=True, learning_rate=1e-4):
        #TODO figure out peephole again or scrap it
        self.hidden_dim = hidden_dim
        self.x_dim = x_dim
        self.concat_dim = hidden_dim + x_dim
        self.init = init
        self.init_params()
        self.grad_clip = grad_clip
        self.peephole = peephole
        self.learning_rate = learning_rate
        self.funcs = {
            'c': {'a': tanh, 'd': d_tanh},
            'u': {'a': sigmoid, 'd': d_sigmoid},
            'o': {'a': sigmoid, 'd': d_sigmoid},
            'f': {'a': sigmoid, 'd': d_sigmoid},
        }

    def init_params(self):
        self.params = {
            k: {'w': self.init((self.hidden_dim, self.concat_dim)),
                'b': np.zeros((self.hidden_dim, 1))} 
                for k in ['c', 'u', 'o', 'f']
        }

    def init_grads(self):
        return {
            k: {'w': np.zeros_like(self.params[k]['w']),
                'b': np.zeros_like(self.params[k]['b'])}
                for k in ['c', 'u', 'o', 'f']
        }   

    def forward(self, x, a_prev, c_prev):
        a_prev = a_prev if a_prev is not None else np.zeros((self.hidden_dim, x.shape[0]))
        c_prev = c_prev if c_prev is not None else np.zeros((self.hidden_dim, x.shape[0]))
        state = {}
        state['c_in'] = c_prev
        state['z'] = np.vstack((x.T, a_prev))
        cache = {}
        for k, func in self.funcs.items():
            state[k], cache[k] = func['a'](np.dot(self.params[k]['w'], state['z']) + self.params[k]['b'])
        state['c_out'] = state['f'] * c_prev + state['u'] * state['c']
        state['a_out'] = state['o'] * tanh(state['c_out'])[0]
        return state, cache

    def backward(self, state, da_next, dc_next):
        dc_out = state['o'] * da_next + dc_next
        grads = self.init_grads()
        d = {}
        d['c'] = state['c'] * (1 - state['c']) * state['u'] * dc_out
        d['u'] = state['u'] * (1 - state['u']) * state['c_out'] * dc_out
        d['o'] = state['o'] * (1 - state['o']) * state['c'] * da_next
        d['f'] = state['f'] * (1 - state['f']) * state['c_in'] * dc_out
        dz = np.zeros_like(state['z'])
        for gate in ['c', 'u', 'o', 'f']:
            dz += np.dot(self.params[gate]['w'].T, d[gate])
            grads[gate]['b'] = np.sum(d[gate], axis=1, keepdims=True)
            grads[gate]['w'] = np.dot(d[gate], state['z'].T)
        da_in = dz[self.x_dim:]
        dc_in = dc_out * state['f']
        return da_in, dc_in, grads

    def update_params(self, grads):
        for gate in ['c', 'u', 'o', 'f']:
            grads[gate]['w'] = np.clip(grads[gate]['w'], -self.grad_clip, self.grad_clip)
            grads[gate]['b'] = np.clip(grads[gate]['b'], -self.grad_clip, self.grad_clip)
            self.params[gate]['w'] -= grads[gate]['w'] * self.learning_rate
            self.params[gate]['b'] -= grads[gate]['b'] * self.learning_rate