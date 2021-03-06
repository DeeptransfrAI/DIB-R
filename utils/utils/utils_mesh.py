# Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import os
import torch
import numpy as np

##################################################################
# faces begin from 0!!!
def face2edge(facenp_fx3):
    '''
    facenp_fx3, int32
    return edgenp_ex2, int32
    '''
    f1 = facenp_fx3[:, 0:1]
    f2 = facenp_fx3[:, 1:2]
    f3 = facenp_fx3[:, 2:3]
    e1 = np.concatenate((f1, f1, f2), axis=0)
    e2 = np.concatenate((f2, f3, f3), axis=0)
    edgenp_ex2 = np.concatenate((e1, e2), axis=1)
    # sort & unique
    edgenp_ex2 = np.sort(edgenp_ex2, axis=1)
    edgenp_ex2 = np.unique(edgenp_ex2, axis=0)
    return edgenp_ex2


def edge2face(facenp_fx3, edgenp_ex2):
    '''
    facenp_fx3, int32
    edgenp_ex2, int32
    return edgenp_ex2, int32
    this edge is indexed by face
    '''
    fnum = facenp_fx3.shape[0]
    enum = edgenp_ex2.shape[0]
    
    facesort = np.sort(facenp_fx3, axis=1)
    edgesort = np.sort(edgenp_ex2, axis=1)
    edgere_ex2 = np.zeros_like(edgesort)
    for i in range(enum):
        pbe, pen = edgesort[i]
        eid = 0
        for j in range(fnum):
            f1, f2, f3 = facesort[j]
            cond1 = f1 == pbe and f2 == pen
            cond2 = f1 == pbe and f3 == pen
            cond3 = f2 == pbe and f3 == pen
            if cond1 or cond2 or cond3:
                edgere_ex2[i, eid] = j
                eid += 1
    
    return edgere_ex2


def face2pneimtx(facenp_fx3):
    '''
    facenp_fx3, int32
    return pointneighbourmtx, pxp, float32
    will normalize!
    assume it is a good mesh
    every point has more than one neighbour
    '''
    pnum = np.max(facenp_fx3) + 1
    pointneighbourmtx = np.zeros(shape=(pnum, pnum), dtype=np.float32)
    for i in range(3):
        be = i
        en = (i + 1) % 3
        idx1 = facenp_fx3[:, be]
        idx2 = facenp_fx3[:, en]
        pointneighbourmtx[idx1, idx2] = 1
        pointneighbourmtx[idx2, idx1] = 1
    pointneicount = np.sum(pointneighbourmtx, axis=1, keepdims=True)
    assert np.all(pointneicount > 0)
    pointneighbourmtx /= pointneicount
    return pointneighbourmtx


def face2pfmtx(facenp_fx3):
    '''
    facenp_fx3, int32
    reutrn pfmtx, pxf, float32
    '''
    pnum = np.max(facenp_fx3) + 1
    fnum = facenp_fx3.shape[0]
    pfmtx = np.zeros(shape=(pnum, fnum), dtype=np.float32)
    for i, f in enumerate(facenp_fx3):
        pfmtx[f[0], i] = 1
        pfmtx[f[1], i] = 1
        pfmtx[f[2], i] = 1
    return pfmtx


# upsample new points
def meshresample(pointnp_px3, facenp_fx3, edgenp_ex2):
    p1 = pointnp_px3[edgenp_ex2[:, 0], :]
    p2 = pointnp_px3[edgenp_ex2[:, 1], :]
    pmid = (p1 + p2) / 2
    point2np_px3 = np.concatenate((pointnp_px3, pmid), axis=0)
    
    # delete f
    # add 4 new faces
    face2np_fx3 = []
    pnum = np.max(facenp_fx3) + 1
    for f in facenp_fx3:
        p1, p2, p3 = f
        p12 = (edgenp_ex2 == (min(p1, p2), max(p1, p2))).all(axis=1).nonzero()[0] + pnum
        p23 = (edgenp_ex2 == (min(p2, p3), max(p2, p3))).all(axis=1).nonzero()[0] + pnum
        p31 = (edgenp_ex2 == (min(p3, p1), max(p3, p1))).all(axis=1).nonzero()[0] + pnum
        face2np_fx3.append([p1, p12, p31])
        face2np_fx3.append([p12, p2, p23])
        face2np_fx3.append([p31, p23, p3])
        face2np_fx3.append([p12, p23, p31])
    face2np_fx3 = np.array(face2np_fx3, dtype=np.int64)
    return point2np_px3, face2np_fx3


def mtx2tfsparse(mtx):
    m, n = mtx.shape
    rows, cols = np.nonzero(mtx)
    # N = rows.shape[0]
    # value = np.ones(shape=(N,), dtype=np.float32)
    value = mtx[rows, cols]
    v = torch.FloatTensor(value)
    i = torch.LongTensor(np.stack((rows, cols), axis=0))
    tfspmtx = torch.sparse.FloatTensor(i, v, torch.Size([m, n]))
    return tfspmtx


################################################################
def loadobj(meshfile):

    v = []
    f = []
    meshfp = open(meshfile, 'r')
    for line in meshfp.readlines():
        data = line.strip().split(' ')
        data = [da for da in data if len(da) > 0]
        if len(data) != 4:
            continue
        if data[0] == 'v':
            v.append([float(d) for d  in data[1:]])
        if data[0] == 'f':
            data = [da.split('/')[0] for da in data]
            f.append([int(d) for d in data[1:]])
    meshfp.close()

    # torch need int64
    facenp_fx3 = np.array(f, dtype=np.int64) - 1
    pointnp_px3 = np.array(v, dtype=np.float32)
    return pointnp_px3, facenp_fx3


def loadobjcolor(meshfile):
    v = []
    f = []
    meshfp = open(meshfile, 'r')
    for line in meshfp.readlines():
        data = line.strip().split(' ')
        data = [da for da in data if len(da) > 0]
        if len(data) != 4 and len(data) != 7:
            continue
        if data[0] == 'v':
            v.append([float(d) for d in data[1:4]])
        if data[0] == 'f':
            data = [da.split('/')[0] for da in data]
            f.append([int(d) for d in data[1:]])
    meshfp.close()

    # torch need int64
    facenp_fx3 = np.array(f, dtype=np.int64) - 1
    pointnp_px3 = np.array(v, dtype=np.float32)
    return pointnp_px3, facenp_fx3


def loadobjtex(meshfile):
    
    v = []
    vt = []
    f = []
    ft = []
    meshfp = open(meshfile, 'r')
    for line in meshfp.readlines():
        data = line.strip().split(' ')
        data = [da for da in data if len(da) > 0]
        if len(data) != 4:
            continue
        if data[0] == 'v':
            v.append([float(d) for d  in data[1:]])
        if data[0] == 'vt':
            vt.append([float(d) for d  in data[1:]])
        if data[0] == 'f':
            data = [da.split('/') for da in data]
            f.append([int(d[0]) for d in data[1:]])
            ft.append([int(d[1]) for d in data[1:]])
    meshfp.close()
    
    # torch need int64
    facenp_fx3 = np.array(f, dtype=np.int64) - 1
    ftnp_fx3 = np.array(ft, dtype=np.int64) - 1
    pointnp_px3 = np.array(v, dtype=np.float32)
    uvs = np.array(vt, dtype=np.float32)[:, :2]
    return pointnp_px3, facenp_fx3, uvs, ftnp_fx3


def savemesh(pointnp_px3, facenp_fx3, fname, partinfo=None):
    
    if partinfo is None:
        fid = open(fname, 'w')
        for pidx, p in enumerate(pointnp_px3):
            pp = p
            fid.write('v %f %f %f\n' % (pp[0], pp[1], pp[2]))
        for f in facenp_fx3:
            f1 = f + 1
            fid.write('f %d %d %d\n' % (f1[0], f1[1], f1[2]))
        fid.close()
    else:
        fid = open(fname, 'w')
        for pidx, p in enumerate(pointnp_px3):
            if partinfo[pidx, -1] == 0:
                pp = p
                color = [1, 0, 0]
            else:
                pp = p
                color = [0, 0, 1]
            fid.write('v %f %f %f %f %f %f\n' % (pp[0], pp[1], pp[2], color[0], color[1], color[2]))
        for f in facenp_fx3:
            f1 = f + 1
            fid.write('f %d %d %d\n' % (f1[0], f1[1], f1[2]))
        fid.close()
    return


def savemeshcolor(pointnp_px3, facenp_fx3, fname, color_px3=None):
    
    if color_px3 is None:
        fid = open(fname, 'w')
        for pidx, p in enumerate(pointnp_px3):
            pp = p
            fid.write('v %f %f %f\n' % (pp[0], pp[1], pp[2]))
        for f in facenp_fx3:
            f1 = f + 1
            fid.write('f %d %d %d\n' % (f1[0], f1[1], f1[2]))
        fid.close()
    else:
        fid = open(fname, 'w')
        for pidx, p in enumerate(pointnp_px3):
            pp = p
            color = color_px3[pidx]
            fid.write('v %f %f %f %f %f %f\n' % (pp[0], pp[1], pp[2], color[0], color[1], color[2]))
        for f in facenp_fx3:
            f1 = f + 1
            fid.write('f %d %d %d\n' % (f1[0], f1[1], f1[2]))
        fid.close()
    return


def p2f(points_px3, faces_fx3):

    ##########################################################
    # 1 points
    pf0_bxfx3 = points_px3[faces_fx3[:, 0], :]
    pf1_bxfx3 = points_px3[faces_fx3[:, 1], :]
    pf2_bxfx3 = points_px3[faces_fx3[:, 2], :]
    # import ipdb
    # ipdb.set_trace()
    points3d_bxfx9 = np.concatenate((pf0_bxfx3, pf1_bxfx3, pf2_bxfx3), axis= -1)

    return points3d_bxfx9


def savemesh_facecolor(pointnp_px3, facenp_fx3, fname, color_px9=None):
    pointnp_px9 = p2f(pointnp_px3, facenp_fx3)
    # import ipdb
    # ipdb.set_trace()

    fid = open(fname, 'w')
    for pidx, p in enumerate(pointnp_px9):
        pp = p
        color = color_px9[pidx]
        for i_point in range(3):
            fid.write('v %f %f %f %f %f %f\n' % (pp[i_point * 3 + 0], pp[i_point * 3 + 1], pp[i_point * 3 + 2],
                                                 color[i_point * 3], color[i_point * 3 + 1], color[i_point * 3 + 2]))
    for f_idx in range(pointnp_px9.shape[0]):
        fid.write('f %d %d %d\n' % (f_idx * 3 + 1, f_idx * 3 + 2, f_idx * 3 + 3))

    fid.close()
def saveobjscale(meshfile, scale, maxratio, shift=None):
    
    mname, prefix = os.path.splitext(meshfile)
    mnamenew = '%s-%.2f%s' % (mname, maxratio, prefix)
    
    meshfp = open(meshfile, 'r')
    meshfp2 = open(mnamenew, 'w')
    for line in meshfp.readlines():
        data = line.strip().split(' ')
        data = [da for da in data if len(da) > 0]
        if len(data) != 4:
            meshfp2.write(line)
            continue
        else:
            if data[0] == 'v':
                p = [scale * float(d) for d  in data[1:]]
                meshfp2.write('v %f %f %f\n' % (p[0], p[1], p[2]))
            else:
                meshfp2.write(line)
                continue
                
    meshfp.close()
    meshfp2.close()
    
    return

