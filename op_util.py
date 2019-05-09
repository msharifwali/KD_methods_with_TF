import tensorflow as tf
from tensorflow.python.ops import control_flow_ops

def Optimizer_w_Distillation(class_loss, LR, epoch, init_epoch, global_step, Distillation):
    with tf.variable_scope('Optimizer_w_Distillation'):
        # get variables and update operations
        variables  = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        
        # make optimizer w/ learning rate scheduler
        optimize = tf.train.MomentumOptimizer(LR, 0.9, use_nesterov=True)
        if Distillation is None:
            # training main-task
            total_loss = class_loss + tf.add_n(tf.losses.get_regularization_losses())
            tf.summary.scalar('loss/total_loss', total_loss)
            gradients  = optimize.compute_gradients(total_loss, var_list = variables)
            
        elif Distillation == 'Soft_logits':
            # multi-task learning with alpha
            total_loss = class_loss*0.7 + tf.add_n(tf.losses.get_regularization_losses()) + tf.add_n(tf.get_collection('dist'))*0.3
            tf.summary.scalar('loss/total_loss', total_loss)
            gradients  = optimize.compute_gradients(total_loss, var_list = variables)
        elif Distillation == 'AT':
            # simple multi-task learning
            total_loss = class_loss + tf.add_n(tf.losses.get_regularization_losses()) + tf.add_n(tf.get_collection('dist'))
            tf.summary.scalar('loss/total_loss', total_loss)
            gradients  = optimize.compute_gradients(total_loss, var_list = variables)
            
        elif Distillation == 'FitNet' or Distillation == 'FSP' or Distillation == 'AB':
            # initialization and fine-tuning
            # in initialization phase, weight decay have to be turn-off which is not trained by distillation
            reg_loss = tf.add_n(tf.losses.get_regularization_losses())
            distillation_loss = tf.add_n(tf.get_collection('dist'))
            transfer = tf.cond(epoch < init_epoch, lambda : 0., lambda : 1.)
            
            total_loss = class_loss*transfer + reg_loss + distillation_loss*(1-transfer)
            tf.summary.scalar('loss/total_loss', total_loss)
            tf.summary.scalar('loss/distillation_loss', distillation_loss)
            gradients  = optimize.compute_gradients(class_loss,             var_list = variables)
            gradient_wdecay = optimize.compute_gradients(reg_loss,          var_list = variables)
            gradient_dist   = optimize.compute_gradients(distillation_loss, var_list = variables)
            
            with tf.variable_scope('clip_grad'):
                for i, gc, gw, gd in zip(range(len(gradients)),gradients,gradient_wdecay,gradient_dist):
                    gw = 0. if gw[0] is None else gw[0]
                    if gd[0] != None:
                        gradients[i] = (gc[0]*transfer + gw + gd[0]*(1-transfer), gc[1])
                    else:
                        gradients[i] = (gc[0]*transfer + gw*transfer, gc[1])
            
        elif Distillation == 'KD-SVD':
            # multi-task learning w/ distillation gradients clipping
            # distillation gradients are clipped by norm of main-task gradients
            def sigmoid(x, k, d = 1):
                s = 1/(1+tf.exp(-(x-k)/d))
                s = tf.cond(tf.greater(s,1-1e-8),
                            lambda : 1.0, lambda : s)
                return s
            
            reg_loss = tf.add_n(tf.losses.get_regularization_losses())
            distillation_loss = tf.add_n(tf.get_collection('dist'))
            
            total_loss = class_loss + reg_loss + distillation_loss
            tf.summary.scalar('loss/total_loss', total_loss)
            tf.summary.scalar('loss/distillation_loss', distillation_loss)
            gradients  = optimize.compute_gradients(class_loss,             var_list = variables)
            gradient_wdecay = optimize.compute_gradients(reg_loss,          var_list = variables)
            gradient_dist   = optimize.compute_gradients(distillation_loss, var_list = variables)
            
            with tf.variable_scope('clip_grad'):
                for i, gc, gw, gd in zip(range(len(gradients)),gradients,gradient_wdecay,gradient_dist):
                    gw = 0. if gw[0] is None else gw[0]
                    if gd[0] != None:
                        norm = tf.sqrt(tf.reduce_sum(tf.square(gc[0])))*sigmoid(epoch, 0)
                        gradients[i] = (gc[0] + gw + tf.clip_by_norm(gd[0], norm), gc[1])
                    else:
                        gradients[i] = (gc[0] + gw, gc[1])
        
        # merge update operators and make train operator
        update_ops.append(optimize.apply_gradients(gradients, global_step=global_step))
        update_op = tf.group(*update_ops)
        train_op = control_flow_ops.with_dependencies([update_op], total_loss, name='train_op')
        return train_op
